/*
 * native/libusb_probe.c
 * ======================
 * 🆕 v0.0.6: pyusb/PySide6を一切経由せず、libusb-1.0のCライブラリを直接呼んで
 * 接続中のUSBデバイスを列挙するだけの、最小限の独立した診断ツール。
 *
 * なぜこれが要るか
 * -----------------
 * pyside6_webusb.diagnostics.environment_report() は「pyusbのget_backend()が
 * Noneを返す」ことを検出できるが、その原因が(a) OS自体にlibusbがそもそも
 * 入っていない、のか (b) libusb自体は正常なのにpyusb側のバックエンド探索
 * ロジックがそれを見つけられていないだけ、なのかを、Pythonの中だけからでは
 * 区別できない場合がある(pyusbは複数のバックエンド候補を試行し、環境変数や
 * ライブラリ探索パスの状態に依存するため)。本プログラムはpyusbを一切経由
 * せず、libusb-1.0のCヘッダ(<libusb-1.0/libusb.h>)を直接includeしlibusb関数を
 * 直接呼ぶことで、「libusb自体は動くか」だけを問う、pyusbからも独立した
 * 第三者的な確認手段を提供する——実際にこのファイルはgcc + libusb-1.0-0-dev
 * だけでビルド・実行し、libusb_init()の成功可否とlibusb_get_device_list()の
 * 結果(接続台数・各デバイスのVID/PID)を標準出力に表示することを確認済み。
 *
 * native/pyside6_webusb_accel/(Rustのpyo3拡張)と同じく、本パッケージの
 * 動作に必須ではない完全にオプショナルな道具であり、通常のインストール
 * ビルドプロセス(pip install / setuptools)には一切組み込まれない——
 * 必要な人が手動でビルドして使う、上級者向けの追加診断手段の位置づけ。
 *
 * ビルド方法(Linux/macOS、libusb-1.0の開発ヘッダが必要):
 *     cc -O2 -Wall -Wextra -o libusb_probe native/libusb_probe.c \
 *         $(pkg-config --cflags --libs libusb-1.0)
 *     ./libusb_probe
 *
 * ビルド方法(pkg-configが無い環境向けの代替):
 *     cc -O2 -Wall -Wextra -o libusb_probe native/libusb_probe.c -lusb-1.0
 *
 * 実際にこの2通りのビルドコマンドの前者(pkg-config経由)で、gcc 13.3.0 +
 * libusb-1.0.27環境においてコンパイル・リンク・実行(接続台数0の環境で
 * 「devices found: 0」を正しく表示、終了コード0)まで確認済み。
 *
 * Windows向けの注記: libusb-1.0のWindows向けバイナリ配布(vcpkg等)を使えば
 * MSVC/MinGWでもビルド可能なはずだが、本パッケージの開発環境では未確認
 * (README/CHANGELOGの「実機確認済み」表記の対象外)。
 */
#include <stdio.h>
#include <libusb-1.0/libusb.h>

int main(void) {
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc != LIBUSB_SUCCESS) {
        fprintf(stderr, "libusb_init failed: %s\n", libusb_error_name(rc));
        return 1;
    }

    const struct libusb_version *ver = libusb_get_version();
    printf("libusb version: %d.%d.%d%s\n", ver->major, ver->minor, ver->micro,
           (ver->rc && ver->rc[0]) ? ver->rc : "");

    libusb_device **list = NULL;
    ssize_t count = libusb_get_device_list(ctx, &list);
    if (count < 0) {
        /* libusb_get_device_list()は失敗時、負のlibusb_error値をssize_tへ
         * 詰めて返す(ヘッダのコメントに明記された仕様)。 */
        fprintf(stderr, "libusb_get_device_list failed: %s\n",
                libusb_error_name((int)count));
        libusb_exit(ctx);
        return 1;
    }

    printf("devices found: %zd\n", count);
    for (ssize_t i = 0; i < count; i++) {
        struct libusb_device_descriptor desc;
        int desc_rc = libusb_get_device_descriptor(list[i], &desc);
        if (desc_rc != LIBUSB_SUCCESS) {
            /* 個々のデバイスの記述子取得に失敗しても(壊れた/変則的な機器の
             * 可能性がある——hardening.pyのbuild_configurations_tree()が
             * Python側で同じ考え方を取っているのと同様)、残りの列挙自体は
             * 続ける。 */
            printf("  [%zd] <failed to read descriptor: %s>\n", i,
                   libusb_error_name(desc_rc));
            continue;
        }
        printf("  [%zd] VID:%04x PID:%04x\n", i, desc.idVendor, desc.idProduct);
    }

    libusb_free_device_list(list, 1 /* unref_devices */);
    libusb_exit(ctx);
    return 0;
}
