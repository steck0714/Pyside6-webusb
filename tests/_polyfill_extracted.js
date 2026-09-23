
(function() {
    'use strict';
    if (navigator.usb) return;  // 既にネイティブAPIがあれば上書きしない（将来Qtが対応した場合の保険）
    if (typeof qt === 'undefined' || !qt.webChannelTransport) return;  // QWebChannel未提供の文脈では何もしない
    // 🛡️ 本物のWebUSB同様、セキュアコンテキスト(https/localhost)以外では一切定義しない。
    if (typeof window.isSecureContext !== 'undefined' && !window.isSecureContext) return;

    var _bridgeReady = new Promise(function(resolve) {
        try {
            new QWebChannel(qt.webChannelTransport, function(channel) {
                resolve(channel.objects.pyUsbBridge || null);
            });
        } catch (e) { resolve(null); }
    });

    function callBridge(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        return _bridgeReady.then(function(bridge) {
            if (!bridge) throw new Error('WebUSB bridge unavailable');
            return new Promise(function(resolve) {
                bridge[method].apply(bridge, args.concat([function(res) { resolve(JSON.parse(res)); }]));
            });
        });
    }

    // 🛡️ frame_origin.FrameOriginTracker がPython側から
    //    runJavaScript('window.__pyUsbFrameToken = "...";') で書き込む値。
    //    これをPython側のオリジン判定(WebUSBBridge._current_origin())へ渡すことで、
    //    このフレームが本当は誰なのかをQt/Chromium自身の判定に基づいて特定できる
    //    (このスクリプト自身がwindow.location.originを自己申告するのではない --
    //    素のQWebChannelオブジェクトを直接叩く敵対的なコードに対しても安全)。
    //    ページ読み込み直後、トークンがまだ届いていない短い時間帯は空文字になり、
    //    その間の呼び出しはPython側で「オリジン不明」として安全に拒否される。
    function _frameToken() {
        return window.__pyUsbFrameToken || '';
    }

    // 🚚 大容量転送対応(v0.0.4a0, WebADB等を想定): 旧実装はhex文字列
    //    (1バイト→2文字、2倍膨張)でブリッジとやり取りしていたが、base64
    //    (1バイト→約1.33文字)に切り替えて往復するJSON文字列サイズを抑える。
    //    ⚠️ チャンク分割が必須: String.fromCharCode.apply(null, bytes)へ配列を
    //    「分割せず丸ごと」渡すと、各バイトが個別の関数引数として展開される
    //    ため、エンジンの引数上限(V8実測: 数十万バイト規模で
    //    'RangeError: Maximum call stack size exceeded')を超えて例外になる。
    //    WebADBのような数百KB〜数MB級のペイロードは容易にこの閾値を超える
    //    ため、0x8000バイトずつのチャンクに分けて処理する。
    function bytesToBase64(view) {
        var arr = view instanceof ArrayBuffer ? new Uint8Array(view) :
                   (view.buffer ? new Uint8Array(view.buffer, view.byteOffset || 0, view.byteLength) : new Uint8Array(view));
        var binary = '';
        var chunkSize = 0x8000;
        for (var i = 0; i < arr.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, arr.subarray(i, i + chunkSize));
        }
        return btoa(binary);
    }
    function base64ToUint8(b64) {
        var binary = atob(b64 || '');
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return bytes;
    }

    // 🛡️ 実仕様(wicg.github.io/webusb#dom-usb-requestdevice)の
    //    「A USBDeviceFilter filter is valid」をそのまま再現。より上位の
    //    フィールドを伴わない下位フィールドの指定はTypeErrorで拒否する対象
    //    (例: vendorId無しでproductIdだけを指定 等)。
    function isValidUsbDeviceFilter(f) {
        if (!f || typeof f !== 'object') return false;
        if (('productId' in f) && !('vendorId' in f)) return false;
        if (('subclassCode' in f) && !('classCode' in f)) return false;
        if (('protocolCode' in f) && !('subclassCode' in f)) return false;
        return true;
    }

    // 🛡️ 実WebUSB仕様(wicg.github.io/webusb)を確認して比較した結果に基づく修正。
    //    claimInterface()は仕様上「保護対象クラスによる拒否」だけがSecurityError、
    //    それ以外(ハンドル不正・libusb側のclaim失敗等)はNetworkErrorが正しい
    //    (open()の「ブロックリスト機器による拒否」も同様にSecurityErrorが正しい)。
    //    requestDeviceChooser()の「チューザーが既に開いている」再入防止ガードは
    //    InvalidStateErrorが正しい(操作を受け付けられる状態ではない、という
    //    一般的なDOMException用法に合わせた)。
    //    Python側はこれらの拒否理由の場合にだけエラー文字列の先頭へ対応する
    //    "XxxError:"を付けて返す取り決めなので、ここではそのプレフィックスだけを見て
    //    DOMExceptionの種別を仕様どおりに振り分ける。それ以外の失敗はメソッドごとの
    //    デフォルト(通常はNetworkError)のままにする。
    // 🛡️ バグ修正(v0.0.4b2, 実Chrome/Blinkソース精査中に発覚): このリストは
    //    元々'SecurityError:'/'InvalidStateError:'の2つしか無く、Python側
    //    (errors.py)が実際に生成しうる 'NotFoundError:' / 'InvalidAccessError:' /
    //    'IndexSizeError:' / 'DataError:' が一切ここで振り分けられていなかった。
    //    該当した場合、DOMExceptionの.nameが(呼び出し元がdefaultErrorNameを
    //    明示していない限り)本来と違う既定値(通常'NetworkError')になり、
    //    かつ.messageの先頭に"IndexSizeError: "のような接頭辞がそのまま
    //    残ってしまう(=ページ側が.nameで正しく分岐できず、メッセージ文面も
    //    おかしい)という実害のあるバグだった。errors.py側で定義している
    //    プレフィックスを漏れなくここに列挙するのが正しい対処であり、
    //    個々の呼び出し箇所でdefaultErrorNameを都度指定する方式は今回のように
    //    漏れが生まれやすいため採らない。
    // 🛡️ security_audit No.2b: Python側(requestDeviceChooser)がfilters/
    //    exclusionFiltersの構造検証を素のQWebChannel直叩きに対する最終防衛
    //    として追加したことに伴う対応。実仕様(wicg.github.io/webusb)では、
    //    無効なUSBDeviceFilterは(下のisValidUsbDeviceFilterによるJS側の
    //    正規チェックと同様)DOMExceptionではなく組み込みの TypeError に
    //    なるべきものなので、'TypeError:'プレフィックスだけは他と扱いを分け、
    //    DOMExceptionではなく本物のTypeErrorとしてthrowする。
    var KNOWN_ERROR_PREFIXES = [
        'SecurityError:', 'InvalidStateError:', 'NotFoundError:',
        'InvalidAccessError:', 'IndexSizeError:', 'DataError:',
    ];
    function throwFromResult(res, defaultMessage, defaultErrorName) {
        var msg = (res && res.error) || defaultMessage;
        var name = defaultErrorName || 'NetworkError';
        if (typeof msg === 'string' && msg.indexOf('TypeError:') === 0) {
            throw new TypeError(msg.slice('TypeError:'.length).trim());
        }
        if (typeof msg === 'string') {
            for (var i = 0; i < KNOWN_ERROR_PREFIXES.length; i++) {
                var prefix = KNOWN_ERROR_PREFIXES[i];
                if (msg.indexOf(prefix) === 0) {
                    name = prefix.slice(0, -1); // 末尾の ':' を落とす
                    msg = msg.slice(prefix.length).trim();
                    break;
                }
            }
        }
        throw new DOMException(msg, name);
    }

    // 🛡️ 実仕様のUSBInterface.alternate/.claimedを再現する。
    //    Python側(webusb_hardening.build_configurations_tree)はinterfaceNumberごとに
    //    alternates配列だけを組み立てて返すため、「今どのalternateが有効か」
    //    「このインターフェースは今claim済みか」はJS側で補う必要がある。
    //    MDN: 「USBInterface.alternate ... By default this is the USBAlternateInterface
    //    from alternates with alternateSetting equal to 0.」を再現(先頭要素決め打ちではなく
    //    alternateSetting===0を探す。無ければ安全側で先頭にフォールバック)。
    function deriveInterfaceState(configurations) {
        (configurations || []).forEach(function(cfg) {
            (cfg.interfaces || []).forEach(function(iface) {
                var alts = iface.alternates || [];
                var zero = alts.filter(function(a) { return a.alternateSetting === 0; })[0];
                iface.alternate = zero || alts[0] || null;
                if (typeof iface.claimed !== 'boolean') iface.claimed = false;
            });
        });
        return configurations;
    }

    function setInterfaceClaimed(device, interfaceNumber, claimed) {
        var iface = ((device.configuration && device.configuration.interfaces) || [])
            .filter(function(i) { return i.interfaceNumber === interfaceNumber; })[0];
        if (iface) iface.claimed = claimed;
    }

    function OpenWebUSBDevice(info) {
        info = info || {};
        this.vendorId = info.vendorId;
        this.productId = info.productId;
        this.productName = info.productName || null;
        this.manufacturerName = info.manufacturerName || null;
        this.serialNumber = info.serialNumber || null;
        this.deviceClass = info.deviceClass || 0;
        this.deviceSubclass = info.deviceSubclass || 0;
        this.deviceProtocol = info.deviceProtocol || 0;
        this.usbVersionMajor = info.usbVersionMajor || 0;
        this.usbVersionMinor = info.usbVersionMinor || 0;
        this.usbVersionSubminor = info.usbVersionSubminor || 0;
        this.deviceVersionMajor = info.deviceVersionMajor || 0;
        this.deviceVersionMinor = info.deviceVersionMinor || 0;
        this.deviceVersionSubminor = info.deviceVersionSubminor || 0;
        this.configurations = deriveInterfaceState(info.configurations || []);
        // 実仕様のconfiguration getterは「bConfigurationValueが現在値と一致するもの」を
        // 都度探す形。Python側(dev.get_active_configuration())が実機の値を
        // activeConfigurationValueとして渡してくればそれを使い、取得できなかった
        // 場合(古いデバイス等)のみ従来どおり先頭要素へ安全側フォールバックする。
        var activeMatch = null;
        if (info.activeConfigurationValue !== undefined && info.activeConfigurationValue !== null) {
            activeMatch = (this.configurations || []).filter(function(c) {
                return c.configurationValue === info.activeConfigurationValue;
            })[0] || null;
        }
        this.configuration = activeMatch || (this.configurations && this.configurations[0]) || null;
        this.opened = false;
        this._handle = null;
    }
    OpenWebUSBDevice.prototype.open = function() {
        // 🛡️ 実Chrome(usb_device.ccのUSBDevice::open())を確認して判明した欠落:
        //    「すでにopened済みなら即座に成功解決する」という冪等性が無かった。
        //    このままだとJS側でopen()を2回呼ぶたびにPython側で新しいハンドルが
        //    発行され続け、1回目のハンドル(claim済みインターフェースの情報を
        //    含む)は self._handle が上書きされて二度と参照できなくなり、
        //    Python側に開いたままのpyusbデバイスリソースとして孤立してしまう
        //    (closeDevice()を呼ぶ手段が失われるリーク)。
        if (this.opened) return Promise.resolve();
        var self = this;
        return callBridge('openDevice', this.vendorId, this.productId, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to open device');
            self._handle = res.handle;
            self.opened = true;
        });
    };
    // 🐛 バグ修正(v0.0.5a3、実仕様のUSBDevice.close()/selectConfiguration()/
    //    reset()アルゴリズムを実際に取得して確認): この3つはいずれも、成功後は
    //    [[claimedInterface]]を全interfaceにわたって全てfalseへリセットすると
    //    定めている(close()は「全claim済みinterfaceに対してreleaseInterface()が
    //    呼ばれたのと同じ状態」、selectConfiguration()/reset()は明示的に
    //    [[claimedInterface]]を全てfalseで埋め直す)。旧実装はPython側
    //    (bridge.py)ではこれを正しく行っていたが、JS側のOpenWebUSBDeviceオブジェクト
    //    自身が持つ各interfaceの.claimed/.alternateはどの経路でもリセットして
    //    いなかった。結果として、例えば「interface 0をclaimし、
    //    selectConfiguration()で別のconfigurationへ移り、元のconfigurationへ
    //    selectConfiguration()で戻る」といった操作をすると、Python側は
    //    正しくclaimed_interfacesを空に戻しているにもかかわらず、JS側の
    //    device.configuration.interfaces[0].claimedはtrueのまま残り続け、
    //    ページ側のコードが「既にclaim済みのはず」と誤認したままbulk/interrupt
    //    転送を試みてNotFoundError(claim済みかつ選択中のalternateとしては
    //    見つからない)になる、という実害のある状態不整合だった。
    function resetAllClaimedInterfaces(device) {
        (device.configurations || []).forEach(function(cfg) {
            (cfg.interfaces || []).forEach(function(iface) {
                iface.claimed = false;
                var alts = iface.alternates || [];
                var zero = alts.filter(function(a) { return a.alternateSetting === 0; })[0];
                iface.alternate = zero || alts[0] || null;
            });
        });
    }
    OpenWebUSBDevice.prototype.close = function() {
        // 🛡️ 実仕様: openedがfalse(既に閉じている/一度も開いていない)なら
        //    ブリッジへは何も送らず、即座に成功解決するno-op。
        if (!this.opened) return Promise.resolve();
        var self = this;
        return _bridgeReady.then(function(bridge) {
            // 🛡️ バグ修正(v0.0.4): frame_tokenを渡し忘れていた。closeDevice()は
            //    Python側で @Slot(int, str) として2引数必須で登録されているため、
            //    1引数(handleのみ)で呼ぶとQWebChannelがスロット呼び出しを黙って
            //    dispatchせず(実機のQWebChannel往復で検証済み)、Python側の
            //    closeDevice()が一度も実行されないままだった。結果としてpyusbの
            //    デバイスハンドルが実際には一切解放されず(_open_devicesにも
            //    残り続け)、close()を呼んでも何も起きていなかった。
            if (bridge && self._handle != null) bridge.closeDevice(self._handle, _frameToken());
            self.opened = false;
            self._handle = null;
            resetAllClaimedInterfaces(self);
        });
    };
    OpenWebUSBDevice.prototype.selectConfiguration = function(configurationValue) {
        var self = this;
        return callBridge('selectConfiguration', this._handle, configurationValue, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to select configuration');
            // 実仕様どおり、選択成功後はconfigurationが新しい設定を指すよう更新する。
            var match = (self.configurations || []).filter(function(c) { return c.configurationValue === configurationValue; })[0];
            if (match) self.configuration = match;
            resetAllClaimedInterfaces(self);
        });
    };
    OpenWebUSBDevice.prototype.claimInterface = function(n) {
        var self = this;
        return callBridge('claimInterface', this._handle, n, _frameToken()).then(function(res) {
            // 保護対象クラスによる拒否だけがSecurityError、それ以外(ハンドル不正・
            // libusb側のclaim失敗)はNetworkErrorが実仕様どおりの振り分け。
            if (!res.success) throwFromResult(res, 'Failed to claim interface');
            setInterfaceClaimed(self, n, true);
        });
    };
    OpenWebUSBDevice.prototype.releaseInterface = function(n) {
        var self = this;
        return callBridge('releaseInterface', this._handle, n, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to release interface');
            setInterfaceClaimed(self, n, false);
        });
    };
    OpenWebUSBDevice.prototype.selectAlternateInterface = function(interfaceNumber, alternateSetting) {
        var self = this;
        return callBridge('selectAlternateInterface', this._handle, interfaceNumber, alternateSetting, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to select alternate interface');
            var iface = ((self.configuration && self.configuration.interfaces) || [])
                .filter(function(i) { return i.interfaceNumber === interfaceNumber; })[0];
            if (iface) {
                var alt = (iface.alternates || []).filter(function(a) { return a.alternateSetting === alternateSetting; })[0];
                if (alt) iface.alternate = alt;
            }
        });
    };
    OpenWebUSBDevice.prototype.reset = function() {
        var self = this;
        return callBridge('resetDevice', this._handle, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to reset device');
            resetAllClaimedInterfaces(self);
        });
    };
    OpenWebUSBDevice.prototype.clearHalt = function(direction, endpointNumber) {
        return callBridge('clearHalt', this._handle, direction, endpointNumber, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Failed to clear halt');
        });
    };
    OpenWebUSBDevice.prototype.forget = function() {
        var self = this;
        return callBridge('forgetGrantedDevice', this.vendorId, this.productId, _frameToken()).then(function() {
            self.opened = false;
        });
    };
    OpenWebUSBDevice.prototype.transferIn = function(endpoint, length) {
        return callBridge('bulkTransferIn', this._handle, endpoint, length, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Transfer failed');
            // 🛡️ 実仕様(USBTransferStatus): STALLはrejectではなくstatus:'stall'を
            //    伴う成功resolveとして返る。Python側がstall検出時はres.statusに
            //    'stall'を入れてくる(それ以外はres.status==='ok')。
            // 🔓 v0.0.4b2: res.warningがあれば(=実Chromeの32MiB上限を超えた等)
            //    DevTools consoleへ警告として転送する。実Chromeを騙るのではなく、
            //    「実Chromeならここでエラーになるが、これはpyside6-webusbなので
            //    続行している」という相違を透明に説明するためのもの
            //    (chrome_transfer_limit_warning()、hardening.py参照)。
            if (res.warning && typeof console !== 'undefined' && console.warn) console.warn(res.warning);
            var bytes = base64ToUint8(res.data || '');
            return { status: res.status || 'ok', data: new DataView(bytes.buffer) };
        });
    };
    OpenWebUSBDevice.prototype.transferOut = function(endpoint, data) {
        var b64 = bytesToBase64(data);
        return callBridge('bulkTransferOut', this._handle, endpoint, b64, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Transfer failed');
            return { status: res.status || 'ok', bytesWritten: res.bytesWritten };
        });
    };
    // 🛡️ spec: isochronousTransferIn/Outはどちらも「対象endpointを探し、
    //    見つからなければNotFoundError、typeがisochronousでなければ
    //    InvalidAccessError」という事前チェックを実機へ問い合わせる前に行う
    //    (USBDevice.isochronousTransferIn(endpointNumber, packetLengths)の
    //    アルゴリズム手順4-6相当)。claim済みのalternateだけを対象にする
    //    (未claimのインターフェースのendpointはそもそも見つからない扱い)。
    function _findClaimedEndpoint(device, endpointNumber, direction) {
        var cfg = device.configuration;
        if (!cfg) return null;
        var interfaces = cfg.interfaces || [];
        for (var i = 0; i < interfaces.length; i++) {
            var iface = interfaces[i];
            if (!iface.claimed) continue;
            var alternates = iface.alternates || [];
            for (var j = 0; j < alternates.length; j++) {
                var endpoints = alternates[j].endpoints || [];
                for (var k = 0; k < endpoints.length; k++) {
                    var ep = endpoints[k];
                    if (ep.endpointNumber === endpointNumber && ep.direction === direction) {
                        return ep;
                    }
                }
            }
        }
        return null;
    }

    OpenWebUSBDevice.prototype.isochronousTransferIn = function(endpointNumber, packetLengths) {
        var ep = _findClaimedEndpoint(this, endpointNumber, 'in');
        if (!ep) {
            return Promise.reject(new DOMException(
                'The specified endpoint is not part of a claimed and selected alternate interface.',
                'NotFoundError'));
        }
        if (ep.type !== 'isochronous') {
            return Promise.reject(new DOMException(
                'The specified endpoint is not an isochronous endpoint.', 'InvalidAccessError'));
        }
        return callBridge('isochronousTransferIn', this._handle, endpointNumber, JSON.stringify(packetLengths), _frameToken())
            .then(function(res) {
                if (!res.success) throwFromResult(res, 'Isochronous transfer failed');
                if (res.warning && typeof console !== 'undefined' && console.warn) console.warn(res.warning);
                var totalLength = 0;
                var packetBytes = (res.packets || []).map(function(p) {
                    var b = base64ToUint8(p.data || '');
                    totalLength += b.length;
                    return b;
                });
                var combined = new Uint8Array(totalLength);
                var offset = 0;
                var packets = packetBytes.map(function(b, i) {
                    combined.set(b, offset);
                    var view = new DataView(combined.buffer, offset, b.length);
                    offset += b.length;
                    return { data: view, status: (res.packets[i] && res.packets[i].status) || 'ok' };
                });
                return { data: new DataView(combined.buffer), packets: packets };
            });
    };
    OpenWebUSBDevice.prototype.isochronousTransferOut = function(endpointNumber, data, packetLengths) {
        var ep = _findClaimedEndpoint(this, endpointNumber, 'out');
        if (!ep) {
            return Promise.reject(new DOMException(
                'The specified endpoint is not part of a claimed and selected alternate interface.',
                'NotFoundError'));
        }
        if (ep.type !== 'isochronous') {
            return Promise.reject(new DOMException(
                'The specified endpoint is not an isochronous endpoint.', 'InvalidAccessError'));
        }
        var b64 = bytesToBase64(data);
        return callBridge('isochronousTransferOut', this._handle, endpointNumber, b64, JSON.stringify(packetLengths), _frameToken())
            .then(function(res) {
                if (!res.success) throwFromResult(res, 'Isochronous transfer failed');
                if (res.warning && typeof console !== 'undefined' && console.warn) console.warn(res.warning);
                return { packets: res.packets || [] };
            });
    };
    OpenWebUSBDevice.prototype.controlTransferIn = function(setup, length) {
        var reqType = (setup.requestType === 'standard' ? 0x00 : setup.requestType === 'class' ? 0x20 : 0x40) |
                      (setup.recipient === 'interface' ? 0x01 : setup.recipient === 'endpoint' ? 0x02 : setup.recipient === 'other' ? 0x03 : 0x00) |
                      0x80; // Device-to-host
        return callBridge('controlTransferIn', this._handle, reqType, setup.request, setup.value, setup.index, length, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Control transfer failed');
            var bytes = base64ToUint8(res.data || '');
            return { status: res.status || 'ok', data: new DataView(bytes.buffer) };
        });
    };
    OpenWebUSBDevice.prototype.controlTransferOut = function(setup, data) {
        var reqType = (setup.requestType === 'standard' ? 0x00 : setup.requestType === 'class' ? 0x20 : 0x40) |
                      (setup.recipient === 'interface' ? 0x01 : setup.recipient === 'endpoint' ? 0x02 : setup.recipient === 'other' ? 0x03 : 0x00);
        var b64 = data ? bytesToBase64(data) : '';
        return callBridge('controlTransferOut', this._handle, reqType, setup.request, setup.value, setup.index, b64, _frameToken()).then(function(res) {
            if (!res.success) throwFromResult(res, 'Control transfer failed');
            return { status: res.status || 'ok', bytesWritten: res.bytesWritten };
        });
    };

    // --- navigator.usb 本体、及びconnect/disconnect イベント ---
    // Python側(PyUsbBridge)がホットプラグ監視タイマーで差分検出し、許可済み
    // オリジンに関係するデバイスの抜き挿しだけをQtシグナルとして送ってくる。
    // 🐛 バグ修正(v0.0.5a3、実DevTools上で `navigator.usb instanceof EventTarget`
    //    が false になることを確認して発覚): 旧実装はEventTargetを継承する
    //    代わりに、addEventListener/removeEventListener/on(connect|disconnect)
    //    プロパティへ個別対応した独自の最小ディスパッチャを実装していた
    //    (types/webusb-polyfill.d.tsは`interface USB extends EventTarget`と
    //    宣言しているにもかかわらず、実行時の実体はただのオブジェクトリテラルで
    //    EventTargetを継承していなかった)。QtWebEngine(実質Chromium)を含む
    //    現代的なJSエンジンはグローバルのEventTargetコンストラクタを持つため、
    //    それを実際に継承したUSBクラス(及びEventを継承した本物の
    //    USBConnectionEvent)へ差し替える。EventTarget自体が存在しない
    //    (極めて古い/簡易な)実行環境向けに、その場合だけ従来の独自
    //    ディスパッチャへフォールバックする防御的な作りにしてある。
    var _HasNativeEventTarget = typeof EventTarget === 'function';

    // ⚠️ EventTarget/EventはES5の「コンストラクタ借用」(Parent.call(this))では
    //    継承できないネイティブのクラスコンストラクタ(`new`無しで呼ぶと
    //    TypeErrorになる実機/Node.js双方で確認済み)。このファイルの他の部分は
    //    意図的にES5関数式スタイルで統一しているが、ネイティブEventTarget/Event
    //    を実際に継承するにはES6の`class ... extends`構文が必須なため、ここだけ
    //    (_HasNativeEventTargetがtrueの、モダンなエンジンだと確定している枝の中でだけ)
    //    使う。フォールバック側は従来どおりのES5スタイルを維持する。
    var USBConnectionEvent, USB;
    if (_HasNativeEventTarget) {
        USBConnectionEvent = class extends Event {
            constructor(type, eventInitDict) {
                super(type, eventInitDict || {});
                this.device = (eventInitDict || {}).device;
            }
        };
        USB = class extends EventTarget {
            constructor() {
                super();
                this.onconnect = null;
                this.ondisconnect = null;
            }
        };
    } else {
        // フォールバック: 素のEventTargetが無い環境向けの最小限の自前実装
        // (instanceof EventTargetにはならないが、機能自体はここまでと同じく動く)。
        USBConnectionEvent = function(type, eventInitDict) {
            var init = eventInitDict || {};
            this.type = type;
            this.device = init.device;
        };
        USB = function() {
            this.onconnect = null;
            this.ondisconnect = null;
        };
        var _fallbackListeners = { connect: [], disconnect: [] };
        USB.prototype.addEventListener = function(type, fn) {
            if (_fallbackListeners[type] && typeof fn === 'function') _fallbackListeners[type].push(fn);
        };
        USB.prototype.removeEventListener = function(type, fn) {
            if (_fallbackListeners[type]) {
                _fallbackListeners[type] = _fallbackListeners[type].filter(function(f) { return f !== fn; });
            }
        };
        USB.prototype.dispatchEvent = function(evt) {
            (_fallbackListeners[evt.type] || []).forEach(function(fn) {
                try { fn(evt); } catch (e) { /* リスナー内の例外はここで握りつぶす(1つの失敗で他を止めない) */ }
            });
            return true;
        };
    }

    navigator.usb = new USB();

    function _dispatchUsbEvent(type, device) {
        var evt = new USBConnectionEvent(type, { device: device });
        try { navigator.usb.dispatchEvent(evt); } catch (e) { /* リスナー内の例外はここで握りつぶす(1つの失敗で他を止めない) */ }
        var handlerProp = 'on' + type;
        if (typeof navigator.usb[handlerProp] === 'function') {
            try { navigator.usb[handlerProp](evt); } catch (e) { /* 同上 */ }
        }
    }
    _bridgeReady.then(function(bridge) {
        if (!bridge) return;
        // 🛡️ security_audit No.5: Python側のdeviceConnected/deviceDisconnected
        // シグナルは、QWebChannelにフレーム単位配信の仕組みが無いため、ページ内の
        // 全フレームへブロードキャストされる。発火条件も「トップレベルページの
        // 許可状況」だけで、"このイベントを受け取っている個々のフレーム自身"の
        // オリジンは一切見ていない(bridge.pyの_poll_hotplug()のコメント参照)。
        // その結果、トップレベルページが許可したデバイスの抜き挿しが、同じページに
        // 埋め込まれた無関係なクロスオリジンiframe(そのデバイスへの許可を一度も
        // 得ていない第三者広告等)にまで届いてしまう。
        // QWebChannel/Qt Signal自体をフレーム単位配信に作り直すことはできないが、
        // 受け取った側であるここで、getDevices()と同じ判定(=このフレーム自身の
        // オリジンが実際にこのvendorId/productIdへの許可を持っているか)を
        // isGrantedToThisFrame()で再検証し、許可が無ければpageへdispatchせずに
        // 静かに捨てる。これによりobservableな挙動としては正しく
        // フレームごとにスコープされる。
        function _dispatchIfGrantedToThisFrame(type, info) {
            try {
                bridge.isGrantedToThisFrame(info.vendorId, info.productId, _frameToken(), function(granted) {
                    if (granted) _dispatchUsbEvent(type, new OpenWebUSBDevice(info));
                });
            } catch (e) { /* 判定できなければ安全側(dispatchしない) */ }
        }
        if (bridge.deviceConnected && bridge.deviceConnected.connect) {
            bridge.deviceConnected.connect(function(infoJson) {
                try { _dispatchIfGrantedToThisFrame('connect', JSON.parse(infoJson)); } catch (e) {}
            });
        }
        if (bridge.deviceDisconnected && bridge.deviceDisconnected.connect) {
            bridge.deviceDisconnected.connect(function(infoJson) {
                try { _dispatchIfGrantedToThisFrame('disconnect', JSON.parse(infoJson)); } catch (e) {}
            });
        }
    });

    // 🐛 v0.0.5a3: 以前はここでnavigator.usbをオブジェクトリテラルとして丸ごと
    // 代入していたが、今はnavigator.usb自体は既に(上でEventTargetを継承した
    // USBのインスタンスとして)生成済みなので、残りのメソッドをその
    // インスタンスへ生やす形にする。addEventListener/removeEventListener/
    // dispatchEventはUSB.prototype側(EventTarget由来、またはフォールバック)に
    // 既にあるため、ここで再定義しない。
    navigator.usb.getDevices = function() {
        return callBridge('listDevices', _frameToken()).then(function(res) {
            return (res.devices || []).map(function(d) { return new OpenWebUSBDevice(d); });
        });
    };
    navigator.usb.requestDevice = function(_options) {
            // 🛡️ 実仕様: USBDeviceRequestOptions.filtersは必須(required)フィールド。
            //    省略された場合、実ブラウザではWebIDLの辞書変換の時点でTypeErrorになる
            //    (wicg.github.io/webusb の USBDeviceRequestOptions定義)。旧実装は
            //    optionsを一切見ておらず、常に全デバイスをチューザーに表示していた。
            if (!_options || !Array.isArray(_options.filters)) {
                return Promise.reject(new TypeError(
                    "Failed to execute 'requestDevice' on 'USB': required member filters is undefined."));
            }
            var exclusionFilters = Array.isArray(_options.exclusionFilters) ? _options.exclusionFilters : [];
            // 🛡️ 実仕様: filters/exclusionFiltersの各要素が「A USBDeviceFilter filter
            //    is valid」に反する場合はTypeErrorで拒否する(例: vendorId無しで
            //    productIdだけを指定 等)。
            var allFilters = _options.filters.concat(exclusionFilters);
            for (var fi = 0; fi < allFilters.length; fi++) {
                if (!isValidUsbDeviceFilter(allFilters[fi])) {
                    return Promise.reject(new TypeError(
                        "Failed to execute 'requestDevice' on 'USB': the provided filter value is invalid."));
                }
            }
            // 🛡️ 本物のWebUSB同様、信頼できるユーザー操作(クリック等)のハンドラ内から
            //    呼ばれた場合のみ受け付ける。navigator.userActivationが無い古い/簡易な
            //    エンジンでは判定できないため、その場合はチェックをスキップする
            //    (その場合でも実際のデバイス選択にはネイティブのチューザーダイアログでの
            //    明示的なユーザー操作が別途必要であり、無許可アクセスには繋がらない)。
            if (typeof navigator.userActivation !== 'undefined' && navigator.userActivation &&
                navigator.userActivation.isActive === false) {
                return Promise.reject(new DOMException(
                    'Must be handling a user gesture to call navigator.usb.requestDevice().', 'SecurityError'));
            }
            // 🛡️ security_audit No.2: 直前で確認した「本物のユーザー操作から
            //    呼ばれている」という事実を、Python側(requestDeviceChooser)が
            //    独立に検証できる形にするため、短命・使い切りのトークンを
            //    発行してもらってから渡す(see: bridge.pyのmintGestureToken/
            //    __init__のself._gesture_tokensのコメント、および既知の限界)。
            //    mintGestureTokenはJSONではなく生のトークン文字列を返す設計
            //    なので、常にJSON.parseする callBridge は使わず直接呼ぶ。
            return _bridgeReady.then(function(bridge) {
                return new Promise(function(resolve) {
                    if (!bridge) return resolve('');
                    bridge.mintGestureToken(function(token) { resolve(token || ''); });
                });
            }).then(function(gestureToken) {
                return callBridge('requestDeviceChooser', JSON.stringify({
                    filters: _options.filters,
                    exclusionFilters: exclusionFilters,
                }), _frameToken(), gestureToken);
            }).then(function(res) {
                if (res.cancelled) {
                    // 🛡️ res.errorがある場合(再入防止ガード発火・pyusbバックエンド不通・
                    //    ダイアログ例外など)は実際の理由を伝える。無い場合(=ユーザーが
                    //    素直にCancelを押した/ダイアログを閉じた)は従来どおり
                    //    汎用のNotFoundErrorにする。
                    if (res.error) throwFromResult(res, 'No device selected.', 'NotFoundError');
                    throw new DOMException('No device selected.', 'NotFoundError');
                }
                if (!res.device) {
                    throw new DOMException('No device selected.', 'NotFoundError');
                }
                return new OpenWebUSBDevice(res.device);
            });
    };

    // 🔧 v0.0.4b2: F12(DevTools Console)向けのデバッグ用ネームスペース。
    // ページを開発中にnavigator.usbの状態を手軽に確認できるユーティリティ集。
    // 🛡️ 安全上の設計方針: ここで公開する情報は「オリジンに紐付かない静的情報
    // (バージョン・Rust高速化の有無・転送上限値)」と「呼び出し元オリジン自身が
    // 既にnavigator.usb.getDevices()経由で見えている情報を見やすく整形しただけの
    // もの」に限定している。他オリジンの許可済みデバイス一覧のような機微情報は
    // 絶対に含めない——install()はこのポリフィル自体をMainWorld(=ページ自身の
    // JSと同じ実行コンテキスト)へ注入するため、ここに書いたものは事実上どの
    // Webページからも(DevTools越しの人間だけでなく、そのページ自身のスクリプト
    // からも)見える。listKnownDevices等の@Slotを外した理由(bridge.py参照)と
    // 全く同じ原則がここにも適用される。
    window.__pysideWebUSB = {
        // 呼び出し元オリジンが既に許可済みのデバイス一覧を、DevTools上で
        // console.table()を使って見やすく表示するショートカット。中身は
        // navigator.usb.getDevices()と完全に同じデータ(=追加の情報開示は無い)。
        listGrantedDevices: function() {
            return navigator.usb.getDevices().then(function(devices) {
                var rows = devices.map(function(d) {
                    return {
                        vendorId: '0x' + d.vendorId.toString(16),
                        productId: '0x' + d.productId.toString(16),
                        productName: d.productName,
                        manufacturerName: d.manufacturerName,
                        serialNumber: d.serialNumber,
                        opened: d.opened,
                    };
                });
                if (typeof console !== 'undefined' && console.table) console.table(rows);
                return rows;
            });
        },

        // 🆕 独自拡張(実Chromeのnavigator.usbには相当機能が無い): このブリッジ
        // 自体の状態(バージョン・Rustアクセラレーションが実際に効いているか・
        // 転送サイズの上限方針)。navigator.usb自体からは通常知りようがない
        // 情報なので、getDevices()の整形と違い、これは純粋にこの実装が
        // 追加で公開している情報。
        bridgeInfo: function() {
            return callBridge('isAvailable').then(function(res) {
                if (typeof console !== 'undefined' && console.log) {
                    console.log('[pyside6-webusb] bridge info:', res);
                }
                return res;
            });
        },

        // 🆕 独自拡張: 実Chromeの32MiB上限(kUsbTransferLengthLimit)をこの
        // 実装がどう扱っているか(拒否ではなく警告に留める方針、
        // hardening.pyのCHROME_USB_TRANSFER_LENGTH_LIMIT/HOST_SAFETY_MAX_
        // TRANSFER_LENGTH参照)をDevTools上で説明する。実際に上限を超えた
        // 転送が起きた際は、この説明を読まなくてもtransferIn/Out自体が
        // console.warn()でその都度知らせる(res.warning、上記callBridge経由の
        // transferIn実装を参照)。
        explainTransferLimits: function() {
            return callBridge('isAvailable').then(function(res) {
                var limits = res.transferLimits || {};
                var msg = '[pyside6-webusb] Transfer size policy: transfers up to ' +
                    limits.hostSafetyHardLimit + ' bytes are allowed here. Real Chrome ' +
                    'would reject anything over ' + limits.chromeCompatibleWarnThreshold +
                    ' bytes with DataError -- this implementation instead logs a ' +
                    'console.warn() on that specific transfer and lets it proceed, since ' +
                    'it is intentionally not a drop-in Chrome clone but a WebUSB-compatible ' +
                    'implementation with its own, more permissive extensions. ' +
                    'See the pyside6-webusb README/CHANGELOG (v0.0.4b2) for the full reasoning.';
                if (typeof console !== 'undefined' && console.log) console.log(msg);
                return limits;
            });
        },
    };
})();
