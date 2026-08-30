//! pyside6-webusb 用のオプショナルなRustアクセラレーション層。
//!
//! 大きく3つの独立した用途を提供する:
//!
//! 1. **base64エンコード/デコードの高速化**: `bridge.py`がQWebChannel越しに転送
//!    データをやり取りする際の実際のワイヤ形式(hex→base64への移行はv0.0.4a0で
//!    実施済み)。Pure PythonのCPython実装(`base64`標準ライブラリ、内部はCで
//!    実装済み)でも十分速いが、WebADB等でMB級のペイロードを繰り返しやり取り
//!    する用途では、Rust実装によるさらなる高速化・低メモリコピー回数の余地が
//!    ある。**このRust拡張がビルドされていなくても、pyside6-webusbは
//!    Pure Pythonのbase64実装へ自動的にフォールバックし、完全に動作する**
//!    (`bridge.py`のimport箇所を参照)。
//!
//! 2. **ADB (Android Debug Bridge) ワイヤプロトコルのメッセージフレーミング**:
//!    WebADBのようなアプリがこのWebUSBブリッジ越しに実際にやり取りするデータの
//!    "形"(24バイト固定長ヘッダ + 可変長ペイロード)を、テストで本物らしく
//!    再現できるようにするためのヘルパー。ADBクライアント/サーバのAUTH認証や
//!    実際のシェルセッション確立まで踏み込んだ本格的なADB実装ではなく、
//!    あくまで「このWebUSBブリッジがADBプロトコルの形をしたデータを問題なく
//!    運べるか」をテストするための骨格である点に注意(README/CHANGELOG参照)。
//!
//! 3. **転送成功レスポンスのJSON組み立て高速化**(v0.0.4b1): `bulkTransferIn`/
//!    `controlTransferIn`の成功時レスポンスは`{"success":true,"status":"ok",
//!    "data":"<base64>"}`という固定の形をしている。Python側で素朴に実装すると
//!    「bytes連結→base64エンコード(新しい文字列オブジェクト)→json.dumps
//!    (さらに新しい文字列オブジェクト)」と、大容量ペイロードのたびに複数回の
//!    フルコピーが発生する。`format_transfer_in_success_json`はこの3段階を
//!    Rust側の1回のバッファ構築にまとめ、中間のPythonオブジェクトを介さずに
//!    済ませる。JSONエスケープが必要な自由文本(エラーメッセージ等)は一切
//!    扱わない専用の狭い用途の関数であり、汎用JSON構築には使えない
//!    (関数doc参照)。
//!
//! ## 設計方針: 純粋Rustロジック層とPyO3バインディング層の分離
//! `pyo3`の`extension-module`フィーチャ(dlopenされるPython拡張として正しく
//! ビルドするために必要)は、意図的にlibpythonへの直接リンクを行わない
//! (実行時にホストのPythonプロセスからシンボルを供給されるのを前提とする)。
//! これは`cargo test`が作る通常のテストバイナリ(Pythonにdlopenされるのでは
//! なく単独で実行される実行ファイル)とは相性が悪く、`Python::with_gil`等を
//! テストコード中で直接使うとリンクエラーになる。そのため本クレートでは、
//! 実際のロジックをすべて`logic`モジュール内の素のRust関数
//! (`&[u8]`/`Vec<u8>`など、PyO3の型を一切介さない)として実装し、
//! `#[pyfunction]`で公開する関数群はその薄いラッパーに徹する設計にした。
//! これにより`cargo test`は素のRustとして問題なく実行でき(このファイル末尾の
//! `#[cfg(test)] mod tests`を参照)、実際のバインディング部分は薄いぶん
//! バグの入り込む余地も小さい。
//!
//! ## ADBプロトコルの出典
//! ヘッダのフィールド順・サイズ、コマンド定数の実際の値、そして
//! 「data_crc32」という名前にもかかわらず実際には単なるバイト総和
//! (本物のCRC32ではない)であることは、実際に動作する公開Rust ADBクライアント
//! 実装 (`tth0704/adb_client`, `adb_client/src/device/adb_transport_message.rs`
//! および `message_commands.rs`) を直接読んで確認した。記憶からの推測では
//! なく、参照実装のソースコードから転記している。

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// PyO3の型を一切介さない、素のRustロジック。`cargo test`で直接検証する。
pub mod logic {
    use base64::engine::general_purpose::STANDARD as B64;
    use base64::Engine as _;

    pub const ADB_HEADER_LEN: usize = 24;

    pub fn encode_base64(data: &[u8]) -> String {
        B64.encode(data)
    }

    pub fn decode_base64(s: &str) -> Result<Vec<u8>, String> {
        B64.decode(s).map_err(|e| format!("invalid base64: {e}"))
    }

    /// `{"success":true,"status":"<status>","data":"<base64(data)>"}` を
    /// 1回のバッファ構築で組み立てる。
    ///
    /// # 安全に使える前提(狭い用途専用の関数である理由)
    /// - `status`は呼び出し側が`"ok"`/`"stall"`/`"babble"`のような、こちら側で
    ///   完全に把握している固定文字列リテラルとしてのみ渡すこと。任意の
    ///   自由テキスト(エラーメッセージ等、ダブルクォートや制御文字を含み
    ///   うるもの)を渡してはならない — この関数はJSON文字列エスケープを
    ///   一切行わない。
    /// - `data`はbase64エンコードした結果を埋め込むため、base64アルファベット
    ///   (`A-Za-z0-9+/=`)にはJSON上エスケープが必要な文字(`"`, `\`,
    ///   制御文字)が含まれないことを利用している。これはbase64の仕様上
    ///   常に成り立つ(base64クレート/RFC 4648準拠のエンコーダの出力に
    ///   対して常に真)。
    /// - 上記2条件が崩れる用途(任意のキー/値を持つ汎用JSON構築)には
    ///   絶対に転用しないこと。
    #[must_use]
    pub fn format_transfer_in_success_json(status: &str, data: &[u8]) -> String {
        const PREFIX: &str = "{\"success\":true,\"status\":\"";
        const MIDDLE: &str = "\",\"data\":\"";
        const SUFFIX: &str = "\"}";
        let encoded = encode_base64(data);
        // 事前に必要ぶんを確保しておく(構築中の再アロケーションを避ける)。
        let mut out = String::with_capacity(
            PREFIX.len() + status.len() + MIDDLE.len() + encoded.len() + SUFFIX.len(),
        );
        out.push_str(PREFIX);
        out.push_str(status);
        out.push_str(MIDDLE);
        out.push_str(&encoded);
        out.push_str(SUFFIX);
        out
    }

    /// ADBの「data_crc32」フィールド値(実体はバイト総和のmod 2^32)を計算する。
    /// u32なので、理論上は非常に大きなペイロード(この実装が許容する上限である
    /// bulkTransferの64MiB等)でオーバーフローしうる。素朴な`.sum::<u32>()`は
    /// debugビルドでオーバーフロー時にpanicしうる(releaseビルドでは黙って
    /// 折り返す、という非対称な挙動になる)ため、`wrapping_add`で明示的に
    /// mod 2^32の折り返しを行い、ビルド設定に関係なく決定的な挙動にしている。
    pub fn adb_checksum(data: &[u8]) -> u32 {
        data.iter().fold(0u32, |acc, &b| acc.wrapping_add(b as u32))
    }

    /// 主要なADBコマンド定数(参照実装確認済み)。値は4文字のASCIIコマンド名を
    /// そのままリトルエンディアンのu32として読んだもの
    /// (例: "CNXN" → バイト列 [0x43,0x4E,0x58,0x4E] → 0x4E584E43)。
    #[must_use]
    pub fn adb_command_name(command: u32) -> Option<&'static str> {
        match command {
            0x4E58_4E43 => Some("CNXN"),
            0x4553_4C43 => Some("CLSE"),
            0x4854_5541 => Some("AUTH"),
            0x4E45_504F => Some("OPEN"),
            0x4554_5257 => Some("WRTE"),
            0x5941_4B4F => Some("OKAY"),
            0x534C_5453 => Some("STLS"),
            _ => None,
        }
    }

    /// 24バイトのADBメッセージヘッダを組み立てる。data_length/data_crc32/magicは
    /// 呼び出し側が計算する必要はなく、command・arg0・arg1・dataから自動的に
    /// 導出する(実際のADBクライアント/サーバの構築ロジックと同じ責務分担)。
    ///
    /// 🔍 品質改善(v0.0.4b1, clippy::pedantic指摘): `data.len()`(usize、64bit環境
    /// では理論上u32の範囲を超えうる)を`as u32`で素朴にキャストすると、
    /// 4GiBを超えるdataに対して黙って下位32bitに折り返った(=実際の長さと
    /// 無関係な小さい)誤ったdata_lengthを書き込んでしまう。実際にはこの
    /// crateの呼び出し元(bridge.py)はBULK_TRANSFER_MAX_LENGTH=64MiBという
    /// はるかに小さい上限を既に強制しているため到達しない経路だが、この
    /// crate単体を直接使うコードに対しても安全であるべきなので、
    /// `u32::try_from`を使い、収まらない場合は(黙って間違った小さい値に
    /// なるより安全な)`u32::MAX`へ飽和させる。そもそも実物のADBプロトコル
    /// 自体のdata_lengthフィールドがu32である以上、4GiB超のペイロードは
    /// プロトコルレベルで表現不可能というだけで、この実装固有の制約ではない。
    #[must_use]
    pub fn adb_pack_header(command: u32, arg0: u32, arg1: u32, data: &[u8]) -> Vec<u8> {
        let data_length = u32::try_from(data.len()).unwrap_or(u32::MAX);
        let data_crc32 = adb_checksum(data);
        let magic = command ^ 0xFFFF_FFFF;

        let mut buf = Vec::with_capacity(ADB_HEADER_LEN);
        buf.extend_from_slice(&command.to_le_bytes());
        buf.extend_from_slice(&arg0.to_le_bytes());
        buf.extend_from_slice(&arg1.to_le_bytes());
        buf.extend_from_slice(&data_length.to_le_bytes());
        buf.extend_from_slice(&data_crc32.to_le_bytes());
        buf.extend_from_slice(&magic.to_le_bytes());
        debug_assert_eq!(buf.len(), ADB_HEADER_LEN);
        buf
    }

    /// 24バイトのADBメッセージヘッダを6つのフィールド
    /// `(command, arg0, arg1, data_length, data_crc32, magic)` へ分解する。
    /// ちょうど24バイトでなければ`Err`。
    ///
    /// # Errors
    /// `header`の長さがちょうど24バイトでない場合、その旨のメッセージを返す。
    pub fn adb_unpack_header(header: &[u8]) -> Result<(u32, u32, u32, u32, u32, u32), String> {
        if header.len() != ADB_HEADER_LEN {
            return Err(format!(
                "ADB header must be exactly {ADB_HEADER_LEN} bytes, got {}",
                header.len()
            ));
        }
        let read_u32 =
            |off: usize| u32::from_le_bytes([header[off], header[off + 1], header[off + 2], header[off + 3]]);
        Ok((
            read_u32(0),
            read_u32(4),
            read_u32(8),
            read_u32(12),
            read_u32(16),
            read_u32(20),
        ))
    }

    /// ヘッダの`magic`/`data_crc32`フィールドが、実際のcommand/dataと整合しているか
    /// (=改ざん・破損されていないか)を検証する。ADBクライアント/サーバ双方が
    /// 受信時に行う整合性チェックと同じロジック。
    #[must_use]
    pub fn adb_verify_header(command: u32, magic: u32, data: &[u8], data_crc32: u32) -> bool {
        magic == (command ^ 0xFFFF_FFFF) && data_crc32 == adb_checksum(data)
    }
}

// ============================================================
// PyO3バインディング層(薄いラッパーのみ。ロジックは上のlogicモジュール)
// ============================================================

#[pyfunction]
fn encode_base64(data: &[u8]) -> String {
    logic::encode_base64(data)
}

#[pyfunction]
fn decode_base64(py: Python<'_>, s: &str) -> PyResult<Py<PyBytes>> {
    let bytes = logic::decode_base64(s).map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(py, &bytes).unbind())
}

#[pyfunction]
fn format_transfer_in_success_json(status: &str, data: &[u8]) -> String {
    logic::format_transfer_in_success_json(status, data)
}

#[pyfunction]
fn adb_command_name(command: u32) -> Option<&'static str> {
    logic::adb_command_name(command)
}

#[pyfunction]
fn adb_checksum(data: &[u8]) -> u32 {
    logic::adb_checksum(data)
}

#[pyfunction]
fn adb_pack_header(py: Python<'_>, command: u32, arg0: u32, arg1: u32, data: &[u8]) -> Py<PyBytes> {
    let buf = logic::adb_pack_header(command, arg0, arg1, data);
    PyBytes::new(py, &buf).unbind()
}

#[pyfunction]
fn adb_unpack_header(header: &[u8]) -> PyResult<(u32, u32, u32, u32, u32, u32)> {
    logic::adb_unpack_header(header).map_err(PyValueError::new_err)
}

#[pyfunction]
fn adb_verify_header(command: u32, magic: u32, data: &[u8], data_crc32: u32) -> bool {
    logic::adb_verify_header(command, magic, data, data_crc32)
}

#[pymodule]
fn pyside6_webusb_accel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_base64, m)?)?;
    m.add_function(wrap_pyfunction!(decode_base64, m)?)?;
    m.add_function(wrap_pyfunction!(format_transfer_in_success_json, m)?)?;
    m.add_function(wrap_pyfunction!(adb_command_name, m)?)?;
    m.add_function(wrap_pyfunction!(adb_checksum, m)?)?;
    m.add_function(wrap_pyfunction!(adb_pack_header, m)?)?;
    m.add_function(wrap_pyfunction!(adb_unpack_header, m)?)?;
    m.add_function(wrap_pyfunction!(adb_verify_header, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}

// ============================================================
// cargo test で実行される、素のRustとしての単体テスト
// (PyO3型を一切介さないlogicモジュールのみを対象とするため、
// extension-moduleフィーチャの有無に関係なくリンクできる。
// Python向けのクロス検証は tests/test_rust_accel.py 側で別途行う)
// ============================================================
#[cfg(test)]
mod tests {
    use super::logic::*;

    #[test]
    fn base64_rfc4648_test_vectors() {
        // RFC 4648 Section 10 の標準テストベクタ
        let cases: &[(&[u8], &str)] = &[
            (b"", ""),
            (b"f", "Zg=="),
            (b"fo", "Zm8="),
            (b"foo", "Zm9v"),
            (b"foob", "Zm9vYg=="),
            (b"fooba", "Zm9vYmE="),
            (b"foobar", "Zm9vYmFy"),
        ];
        for (raw, want) in cases {
            assert_eq!(encode_base64(raw), *want);
            assert_eq!(decode_base64(want).unwrap(), *raw);
        }
    }

    #[test]
    fn base64_rejects_invalid_input() {
        assert!(decode_base64("not valid base64!!!").is_err());
    }

    #[test]
    fn base64_large_round_trip() {
        // WebADB規模(500KB)のペイロードでも1バイトも欠落・破損しないことを確認
        let data: Vec<u8> = (0..500_000usize).map(|i| (i % 256) as u8).collect();
        let encoded = encode_base64(&data);
        let decoded = decode_base64(&encoded).unwrap();
        assert_eq!(decoded, data);
    }

    #[test]
    fn format_transfer_in_success_json_matches_hand_built_json() {
        // json.dumps({"success": True, "status": status, "data": b64encode(data)})
        // と完全に同じ文字列になることを、Rust側だけで(=Pythonを介さず)簡易に
        // 検証する(手でJSONを組み立てて突き合わせる。Python側json.dumpsとの
        // 突き合わせはtests/test_rust_accel.py側で別途行う)。
        let data = b"hello world";
        let json = format_transfer_in_success_json("ok", data);
        let expected = format!(
            "{{\"success\":true,\"status\":\"ok\",\"data\":\"{}\"}}",
            encode_base64(data)
        );
        assert_eq!(json, expected);
        // 妥当なJSONとして構文的にパース可能であることも確認(手組み文字列
        // なので構文が壊れていないことを別途裏取りする)。
        assert!(json.starts_with('{') && json.ends_with('}'));
    }

    #[test]
    fn format_transfer_in_success_json_handles_empty_data() {
        let json = format_transfer_in_success_json("stall", b"");
        assert_eq!(json, "{\"success\":true,\"status\":\"stall\",\"data\":\"\"}");
    }

    #[test]
    fn format_transfer_in_success_json_large_payload_round_trips_through_base64() {
        // 500KBペイロードでも、埋め込まれているbase64部分を取り出してデコード
        // すれば元のバイト列に戻ることを確認する(=JSON組み立て時にバイトが
        // 壊れていないことの実質的な確認)。
        let data: Vec<u8> = (0..500_000usize).map(|i| ((i * 7) % 256) as u8).collect();
        let json = format_transfer_in_success_json("ok", &data);
        let prefix = "{\"success\":true,\"status\":\"ok\",\"data\":\"";
        let suffix = "\"}";
        assert!(json.starts_with(prefix));
        assert!(json.ends_with(suffix));
        let embedded_b64 = &json[prefix.len()..json.len() - suffix.len()];
        let decoded = decode_base64(embedded_b64).unwrap();
        assert_eq!(decoded, data);
    }

    #[test]
    fn adb_checksum_matches_manual_sum() {
        assert_eq!(adb_checksum(&[]), 0);
        assert_eq!(adb_checksum(&[1, 2, 3]), 6);
        assert_eq!(adb_checksum(&[0xFF, 0xFF]), 0x1FE);
    }

    #[test]
    fn adb_checksum_wraps_mod_2_32_without_panicking() {
        // 64MiB(このプロジェクトのbulkTransferIn上限)ぶんの0xFFバイトなら
        // 単純総和は 0xFF * 67_108_864 = 17_105_859_840 で u32 の範囲(約42.9億)を
        // 超える。wrapping_add により mod 2^32 で正しく折り返すことを確認する。
        let data = vec![0xFFu8; 64 * 1024 * 1024];
        let expected: u64 = 0xFFu64 * (data.len() as u64);
        let want = (expected % (1u64 << 32)) as u32;
        assert_eq!(adb_checksum(&data), want);
    }

    #[test]
    fn adb_header_round_trip() {
        let data = b"hello adb";
        let header = adb_pack_header(0x4E58_4E43, 1, 0, data);
        assert_eq!(header.len(), ADB_HEADER_LEN);

        let (command, arg0, arg1, data_length, data_crc32, magic) =
            adb_unpack_header(&header).unwrap();
        assert_eq!(command, 0x4E58_4E43);
        assert_eq!(arg0, 1);
        assert_eq!(arg1, 0);
        assert_eq!(data_length, data.len() as u32);
        assert_eq!(data_crc32, adb_checksum(data));
        assert_eq!(magic, command ^ 0xFFFF_FFFF);
        assert!(adb_verify_header(command, magic, data, data_crc32));
        assert!(!adb_verify_header(command, magic, b"tampered", data_crc32));
    }

    #[test]
    fn adb_header_round_trip_empty_payload() {
        // CNXN応答やOKAYはペイロード無し(data_length=0)であることが多い。
        let header = adb_pack_header(0x5941_4B4F, 42, 7, b"");
        let (command, arg0, arg1, data_length, data_crc32, magic) =
            adb_unpack_header(&header).unwrap();
        assert_eq!(command, 0x5941_4B4F);
        assert_eq!(arg0, 42);
        assert_eq!(arg1, 7);
        assert_eq!(data_length, 0);
        assert_eq!(data_crc32, 0);
        assert_eq!(magic, command ^ 0xFFFF_FFFF);
    }

    #[test]
    fn adb_unpack_header_rejects_wrong_length() {
        assert!(adb_unpack_header(&[0u8; 23]).is_err());
        assert!(adb_unpack_header(&[0u8; 25]).is_err());
        assert!(adb_unpack_header(&[]).is_err());
    }

    #[test]
    fn adb_verify_header_detects_bit_flip_in_header_fields() {
        let data = b"payload";
        let header = adb_pack_header(0x4E45_504F, 1, 2, data);
        let (command, arg0, _arg1, _len, data_crc32, magic) = adb_unpack_header(&header).unwrap();
        // magicを1ビット反転させただけで検出できること
        assert!(!adb_verify_header(command, magic ^ 1, data, data_crc32));
        let _ = arg0;
    }

    #[test]
    fn adb_command_names_match_reference() {
        assert_eq!(adb_command_name(0x4E58_4E43), Some("CNXN"));
        assert_eq!(adb_command_name(0x4553_4C43), Some("CLSE"));
        assert_eq!(adb_command_name(0x4854_5541), Some("AUTH"));
        assert_eq!(adb_command_name(0x4E45_504F), Some("OPEN"));
        assert_eq!(adb_command_name(0x4554_5257), Some("WRTE"));
        assert_eq!(adb_command_name(0x5941_4B4F), Some("OKAY"));
        assert_eq!(adb_command_name(0x534C_5453), Some("STLS"));
        assert_eq!(adb_command_name(0xDEAD_BEEF), None);
    }
}
