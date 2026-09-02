// tests/extract_polyfill_js.py が書き出した _polyfill_extracted.js を、QWebChannel等をモックした
// 最小限のブラウザ風環境でロードし、navigator.usb のロジックを検証する。
const fs = require('fs');
const assert = require('assert');

global.DOMException = class DOMException extends Error {
    constructor(message, name) { super(message); this.name = name || 'Error'; }
};

// --- QWebChannel / bridge のモック ---
let fakeBridgeCalls = [];
let fakeDevices = [{
    vendorId: 0x2341, productId: 0x8036, manufacturerName: 'Acme', productName: 'Widget',
    serialNumber: 'SN1', deviceClass: 0, usbVersionMajor: 2, usbVersionMinor: 0, usbVersionSubminor: 0,
    configurations: [
        {
            configurationValue: 1,
            interfaces: [{
                interfaceNumber: 0,
                // わざと alternateSetting=1 を先頭に置く。「配列の先頭を機械的に使う」誤実装だと
                // これを.alternateとして返してしまう。alternateSetting===0を明示的に
                // 探しているかどうかを区別できるテストにするため。
                alternates: [
                    { alternateSetting: 1, interfaceClass: 0xFF, interfaceSubclass: 0, interfaceProtocol: 0, endpoints: [] },
                    { alternateSetting: 0, interfaceClass: 0xFF, interfaceSubclass: 0, interfaceProtocol: 0,
                      endpoints: [
                          { endpointNumber: 1, direction: 'in', type: 'bulk', packetSize: 64 },
                          { endpointNumber: 3, direction: 'in', type: 'isochronous', packetSize: 32 },
                          { endpointNumber: 4, direction: 'out', type: 'isochronous', packetSize: 32 },
                      ] },
                ],
            }],
        },
        { configurationValue: 2, interfaces: [] },
    ],
}];

let openDeviceResponse = { success: true, handle: 1 };
let claimInterfaceResponse = { success: true };
let bulkTransferInResponse = { success: true, status: 'ok', data: 'AA==' };
let bulkTransferOutResponse = { success: true, status: 'ok', bytesWritten: 1 };
let controlTransferInResponse = { success: true, status: 'ok', data: 'AA==' };
let controlTransferOutResponse = { success: true, status: 'ok', bytesWritten: 1 };
let isochronousTransferInResponse = { success: true, packets: [{ status: 'ok', data: 'AQI=' }, { status: 'ok', data: 'AwQ=' }] };
let isochronousTransferOutResponse = { success: true, packets: [{ status: 'ok', bytesWritten: 2 }, { status: 'ok', bytesWritten: 2 }] };

function makeSignal() {
    const handlers = [];
    return { connect: (fn) => handlers.push(fn), _emit: (v) => handlers.forEach(h => h(v)) };
}
const fakeBridge = {
    deviceConnected: makeSignal(),
    deviceDisconnected: makeSignal(),
    // 🔧 v0.0.4b2: window.__pysideWebUSB.bridgeInfo()/explainTransferLimits()が
    // callBridge('isAvailable')経由でこれを叩く。実際のPython実装
    // (bridge.py, isAvailable())が返す形をそのまま模している。
    isAvailable: function(cb) {
        cb(JSON.stringify({
            available: true,
            bridgeVersion: '0.0.4b2-test',
            rustAccelerated: true,
            transferLimits: {
                chromeCompatibleWarnThreshold: 33554432,
                hostSafetyHardLimit: 536870912,
                controlTransferMaxLength: 65535,
            },
        }));
    },
    listDevices: function(frameToken, cb) { fakeBridgeCalls.push(['listDevices', frameToken]); cb(JSON.stringify({ devices: fakeDevices })); },
    requestDeviceChooser: function(optionsJson, frameToken, cb) {
        fakeBridgeCalls.push(['requestDeviceChooser', optionsJson, frameToken]);
        cb(JSON.stringify({ device: fakeDevices[0] }));
    },
    openDevice: function(vid, pid, frameToken, cb) { fakeBridgeCalls.push(['openDevice', vid, pid, frameToken]); cb(JSON.stringify(openDeviceResponse)); },
    // closeDeviceはPython側で@Slot(int, str)(result=無し)として登録されており、
    // callBridge()を経由しない直接呼び出しのため、他のブリッジ関数と違い
    // コールバック引数(cb)を取らない。
    closeDevice: function(h, frameToken) { fakeBridgeCalls.push(['closeDevice', h, frameToken]); },
    selectConfiguration: function(h, cfg, frameToken, cb) { fakeBridgeCalls.push(['selectConfiguration', h, cfg, frameToken]); cb(JSON.stringify({ success: true })); },
    claimInterface: function(h, n, frameToken, cb) { fakeBridgeCalls.push(['claimInterface', h, n, frameToken]); cb(JSON.stringify(claimInterfaceResponse)); },
    releaseInterface: function(h, n, frameToken, cb) { fakeBridgeCalls.push(['releaseInterface', h, n, frameToken]); cb(JSON.stringify({ success: true })); },
    resetDevice: function(h, frameToken, cb) { fakeBridgeCalls.push(['resetDevice', h, frameToken]); cb(JSON.stringify({ success: true })); },
    clearHalt: function(h, dir, ep, frameToken, cb) { fakeBridgeCalls.push(['clearHalt', h, dir, ep, frameToken]); cb(JSON.stringify({ success: true })); },
    forgetGrantedDevice: function(vid, pid, frameToken, cb) { fakeBridgeCalls.push(['forgetGrantedDevice', vid, pid, frameToken]); cb(JSON.stringify({ success: true })); },
    selectAlternateInterface: function(h, n, alt, frameToken, cb) { fakeBridgeCalls.push(['selectAlternateInterface', h, n, alt, frameToken]); cb(JSON.stringify({ success: true })); },
    bulkTransferIn: function(h, ep, len, frameToken, cb) { fakeBridgeCalls.push(['bulkTransferIn', h, ep, len, frameToken]); cb(JSON.stringify(bulkTransferInResponse)); },
    bulkTransferOut: function(h, ep, dataB64, frameToken, cb) { fakeBridgeCalls.push(['bulkTransferOut', h, ep, dataB64, frameToken]); cb(JSON.stringify(bulkTransferOutResponse)); },
    controlTransferIn: function(h, rt, req, val, idx, len, frameToken, cb) { fakeBridgeCalls.push(['controlTransferIn', h, rt, req, val, idx, len, frameToken]); cb(JSON.stringify(controlTransferInResponse)); },
    controlTransferOut: function(h, rt, req, val, idx, dataB64, frameToken, cb) { fakeBridgeCalls.push(['controlTransferOut', h, rt, req, val, idx, dataB64, frameToken]); cb(JSON.stringify(controlTransferOutResponse)); },
    isochronousTransferIn: function(h, ep, packetLengthsJson, frameToken, cb) { fakeBridgeCalls.push(['isochronousTransferIn', h, ep, packetLengthsJson, frameToken]); cb(JSON.stringify(isochronousTransferInResponse)); },
    isochronousTransferOut: function(h, ep, dataB64, packetLengthsJson, frameToken, cb) { fakeBridgeCalls.push(['isochronousTransferOut', h, ep, dataB64, packetLengthsJson, frameToken]); cb(JSON.stringify(isochronousTransferOutResponse)); },
};

global.qt = { webChannelTransport: {} };
global.QWebChannel = function(transport, cb) {
    setTimeout(() => cb({ objects: { pyUsbBridge: fakeBridge } }), 0);
};
global.window = { isSecureContext: true };
// 注: Node.js 22はfetch互換のため navigator をビルトインの読み取り専用グローバルとして
// 既に持っており、`global.navigator = {...}` による丸ごとの差し替えは反映されない。
// 実ブラウザ(QtWebEngine)ではnavigatorは通常の書き換え可能なオブジェクトなので、
// ここではNode環境の都合に合わせてプロパティを追加する形にする。
if (typeof global.navigator === 'undefined') global.navigator = {};
global.navigator.userActivation = { isActive: true };

const code = fs.readFileSync(require('path').join(__dirname, '_polyfill_extracted.js'), 'utf8');
eval(code);

async function main() {
    await new Promise(r => setTimeout(r, 10)); // _bridgeReady解決待ち

    assert.ok(navigator.usb, 'navigator.usb should be defined');

    const devices = await navigator.usb.getDevices();
    assert.strictEqual(devices.length, 1);
    assert.strictEqual(devices[0].serialNumber, 'SN1', 'serialNumberが記述子から反映されているべき');
    assert.strictEqual(devices[0].usbVersionMajor, 2);
    assert.strictEqual(devices[0].configurations.length, 2);
    console.log('getDevices + rich descriptor: OK');

    // 🛡️ activeConfigurationValue: 複数コンフィグレーションを持つ機器で、
    // Python側(dev.get_active_configuration())が返した実際のアクティブ値に
    // 一致するconfigurationが選ばれているか(常に配列の先頭固定ではないか)を確認する。
    const multiConfigDevice = {
        vendorId: 0x1050, productId: 0x0002, manufacturerName: 'Multi', productName: 'ConfigDevice',
        serialNumber: 'MC1', deviceClass: 0, usbVersionMajor: 2, usbVersionMinor: 0, usbVersionSubminor: 0,
        activeConfigurationValue: 2,
        configurations: [
            { configurationValue: 1, interfaces: [] },
            { configurationValue: 2, interfaces: [] },
        ],
    };
    fakeDevices.push(multiConfigDevice);
    const devicesWithMulti = await navigator.usb.getDevices();
    const mc = devicesWithMulti.filter(d => d.serialNumber === 'MC1')[0];
    assert.ok(mc, 'multiConfigDeviceが見つかるはず');
    assert.strictEqual(mc.configuration.configurationValue, 2,
        'activeConfigurationValue(=2)に一致するconfigurationが選ばれるべき(先頭固定ではない)');
    fakeDevices.pop(); // 後続のテスト(devices.length===1前提など)に影響しないよう元に戻す
    console.log('activeConfigurationValue selects the real active USBConfiguration (not index 0 fixed): OK');

    // 🛡️ 実仕様: USBDeviceRequestOptions.filtersは必須(required)。省略時はTypeError。
    try {
        await navigator.usb.requestDevice({});
        assert.fail('should have thrown TypeError');
    } catch (e) {
        assert.strictEqual(e.name, 'TypeError', 'filters省略はTypeErrorのはず');
    }
    try {
        await navigator.usb.requestDevice();
        assert.fail('should have thrown TypeError');
    } catch (e) {
        assert.strictEqual(e.name, 'TypeError', '引数無しの呼び出しもTypeErrorのはず');
    }
    console.log('requestDevice without filters -> TypeError: OK');

    // 🛡️ 実仕様: 'A USBDeviceFilter filter is valid' に反するフィルタ
    // (例: vendorId無しでproductIdだけを指定)は filters/exclusionFilters どちらでもTypeError。
    try {
        await navigator.usb.requestDevice({ filters: [{ productId: 0x8036 }] });
        assert.fail('should have thrown TypeError');
    } catch (e) {
        assert.strictEqual(e.name, 'TypeError', 'vendorId無しのproductId指定はTypeErrorのはず');
    }
    try {
        await navigator.usb.requestDevice({ filters: [{}], exclusionFilters: [{ subclassCode: 1 }] });
        assert.fail('should have thrown TypeError');
    } catch (e) {
        assert.strictEqual(e.name, 'TypeError', 'exclusionFilters側の不正フィルタもTypeErrorのはず');
    }
    console.log('requestDevice with invalid filter -> TypeError: OK');

    // 🛡️ filters/exclusionFiltersがブリッジへそのまま(構造を保って)渡っているか。
    // 実際の「このデバイスがフィルタに一致するか」の判定はハードウェア記述子を
    // 扱うPython側(webusb_hardening.py: device_matches_usb_filter等、既存のtest_webusb_hardening.py
    // で別途検証済み)の責務なので、JS側では検証(TypeError)+受け渡しまでを確認する。
    fakeBridgeCalls.length = 0;
    await navigator.usb.requestDevice({
        filters: [{ vendorId: 0x2341, productId: 0x8036 }],
        exclusionFilters: [{ vendorId: 0x9999 }],
    });
    const sentOptions = JSON.parse(fakeBridgeCalls.filter(c => c[0] === 'requestDeviceChooser')[0][1]);
    assert.deepStrictEqual(sentOptions.filters, [{ vendorId: 0x2341, productId: 0x8036 }]);
    assert.deepStrictEqual(sentOptions.exclusionFilters, [{ vendorId: 0x9999 }]);
    console.log('requestDevice passes filters/exclusionFilters through to the bridge unchanged: OK');

    fakeBridgeCalls.length = 0; // 以降の「exact sequence」系アサーションのため、ここでクリアしておく

    // 仕様上「全デバイスを見せたい」場合の正しい書き方は filters: [{}] (空オブジェクト = 無条件一致)。
    // filters: [] (空配列)は仕様上「一致するものなし」を意味する点に注意(このモックの
    // requestDeviceChooser自体はoptionsを見ずに常にfakeDevices[0]を返すため、モック単体としては
    // filters:[]でも通ってしまうが、実際のPython実装では何も表示されなくなるため使わない)。
    const dev = await navigator.usb.requestDevice({ filters: [{}] });
    assert.strictEqual(dev.vendorId, 0x2341);
    console.log('requestDevice: OK');

    await dev.open();

    // 🛡️ 実Chrome(usb_device.ccのUSBDevice::open())を確認して判明した欠落:
    //    open()は「すでにopened済みなら即座に成功解決する」冪等性を持つべき。
    //    無いと、open()を2回呼ぶたびにPython側で新しいハンドルが発行され続け、
    //    1回目のハンドル(claim済みインターフェースの情報を含む)がリークする。
    {
        const callsBeforeSecondOpen = fakeBridgeCalls.length;
        assert.strictEqual(dev.opened, true);
        await dev.open();
        assert.strictEqual(fakeBridgeCalls.length, callsBeforeSecondOpen,
            'すでにopened済みの状態でopen()を再度呼んでも、ブリッジへは問い合わせないはず');
        console.log('open() is idempotent when already opened: OK');
    }

    await dev.selectConfiguration(1);
    await dev.releaseInterface(0);
    await dev.reset();
    await dev.clearHalt('in', 1);
    await dev.forget();
    assert.deepStrictEqual(
        fakeBridgeCalls.map(c => c[0]),
        ['requestDeviceChooser', 'openDevice', 'selectConfiguration', 'releaseInterface', 'resetDevice', 'clearHalt', 'forgetGrantedDevice']
    );
    console.log('selectConfiguration/releaseInterface/reset/clearHalt/forget wiring: OK');

    // 🛡️ 実仕様(MDN): 「USBInterface.alternate は既定でalternates中の
    // alternateSetting===0のもの」。fakeDevicesではわざと配列の先頭を
    // alternateSetting=1にしてあるので、先頭を機械的に採用する実装だと
    // ここで失敗するはず。
    const iface0 = dev.configuration.interfaces[0];
    assert.strictEqual(iface0.alternate.alternateSetting, 0, 'alternateはalternateSetting===0を指すべき(配列の先頭ではない)');
    assert.strictEqual(iface0.claimed, false, 'claim前はclaimed=falseのはず');
    console.log('USBInterface.alternate picks alternateSetting===0: OK');

    await dev.claimInterface(0);
    assert.strictEqual(iface0.claimed, true, 'claimInterface成功後はclaimed=trueになるべき');

    assert.strictEqual(iface0.alternate.alternateSetting, 0, 'selectAlternateInterface前の初期状態はalternateSetting===0のはず');
    await dev.selectAlternateInterface(0, 1);
    assert.strictEqual(iface0.alternate.alternateSetting, 1, 'selectAlternateInterface(0,1)後はalternateSetting===1に更新されるはず');
    assert.ok(fakeBridgeCalls.some(c => c[0] === 'selectAlternateInterface' && c[1] === dev._handle && c[2] === 0 && c[3] === 1),
        'ブリッジへ (handle, interfaceNumber, alternateSetting) が正しく渡っているはず');
    console.log('selectAlternateInterface: pyusbのset_interface_altsettingへ実配線・.alternate更新: OK');

    await dev.releaseInterface(0);
    assert.strictEqual(iface0.claimed, false, 'releaseInterface後はclaimed=falseに戻るべき');
    console.log('claimInterface/releaseInterface update .claimed: OK');

    await dev.selectConfiguration(2);
    assert.strictEqual(dev.configuration.configurationValue, 2, 'selectConfiguration後はconfigurationが新しい設定を指すべき');
    console.log('selectConfiguration updates .configuration: OK');

    // 🛡️ 実仕様の比較で見つかった修正点: claimInterface()はSecurityErrorが
    // 「保護対象クラスによる拒否」の場合だけに限定されるべきで、それ以外の
    // 失敗(ここではlibusb側のclaim失敗を想定)はNetworkErrorが正しい
    // (以前は全失敗を一律SecurityErrorにしてしまっていた)。
    claimInterfaceResponse = { success: false, error: 'some generic libusb claim failure' };
    try {
        await dev.claimInterface(0);
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'NetworkError', '保護対象クラス以外の失敗はNetworkErrorのはず');
    }
    claimInterfaceResponse = { success: false, error: "SecurityError: interface 0 is class 'Human Interface Device (HID)' and cannot be claimed by WebUSB" };
    try {
        await dev.claimInterface(0);
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'SecurityError', '保護対象クラスによる拒否はSecurityErrorのはず');
        assert.ok(!e.message.startsWith('SecurityError:'), 'messageからは振り分け用の接頭辞を取り除くべき');
    }
    claimInterfaceResponse = { success: true };
    console.log('claimInterface: SecurityError only for protected-class rejection, NetworkError otherwise: OK');

    // 同じ振り分けがopen()(ブロックリスト拒否)にも適用されているか
    openDeviceResponse = { success: false, error: 'SecurityError: this device is on the protected security-key blocklist and cannot be accessed via WebUSB' };
    const blockedDev = await navigator.usb.requestDevice({ filters: [{}] });
    try {
        await blockedDev.open();
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'SecurityError', 'ブロックリスト拒否はopen()でもSecurityErrorのはず(以前はNetworkError固定だった)');
    }
    openDeviceResponse = { success: true, handle: 1 };
    console.log('open(): blocklist rejection surfaces as SecurityError: OK');

    // 🛡️ isochronous転送: 旧実装は常にNotSupportedErrorだったが、実装した後は
    // spec通りの事前チェック(未claim/存在しない endpoint -> NotFoundError、
    // isochronous以外のtype -> InvalidAccessError)と、成功時のpackets/data組み立てを
    // 確認する。他のテストによるdev/claimInterfaceResponseの状態変化(release済み・
    // config2に切替済み等)の影響を受けないよう、フレッシュなdeviceインスタンスを
    // 取得して検証する。
    claimInterfaceResponse = { success: true };
    const isoDevices = await navigator.usb.getDevices();
    const isoDev = isoDevices[0];

    // 未claimのインターフェースのendpointは「見つからない」扱い(NotFoundError)
    try {
        await isoDev.isochronousTransferIn(3, [32, 32]);
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'NotFoundError', '未claimのインターフェースのendpointはNotFoundErrorのはず');
    }
    console.log('isochronousTransferIn on unclaimed interface -> NotFoundError: OK');

    await isoDev.claimInterface(0);
    await isoDev.selectAlternateInterface(0, 0); // endpoints定義がある方(alternateSetting=0)を選択

    // claim済みだが型がisochronousでないendpoint(endpoint 1はbulk) -> InvalidAccessError
    try {
        await isoDev.isochronousTransferIn(1, [32]);
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'InvalidAccessError', 'isochronous以外のtypeのendpointはInvalidAccessErrorのはず');
    }
    console.log('isochronousTransferIn on non-isochronous endpoint -> InvalidAccessError: OK');

    // 存在しないendpoint番号 -> NotFoundError
    try {
        await isoDev.isochronousTransferIn(9, [32]);
        assert.fail('should have thrown');
    } catch (e) {
        assert.strictEqual(e.name, 'NotFoundError', '存在しないendpoint番号はNotFoundErrorのはず');
    }

    // 正常系: IN方向(endpoint 3, isochronous)
    isochronousTransferInResponse = { success: true, packets: [{ status: 'ok', data: 'AQI=' }, { status: 'ok', data: 'AwQF' }] };
    const isoInResult = await isoDev.isochronousTransferIn(3, [2, 3]);
    assert.ok(fakeBridgeCalls.some(c => c[0] === 'isochronousTransferIn' && c[2] === 3 && c[3] === JSON.stringify([2, 3])),
        'ブリッジへ (handle, endpointNumber, packetLengthsのJSON) が正しく渡っているはず');
    assert.strictEqual(isoInResult.packets.length, 2, 'packetsは要求したpacketLengthsと同じ個数のはず');
    assert.strictEqual(isoInResult.packets[0].status, 'ok');
    assert.strictEqual(new Uint8Array(isoInResult.packets[0].data.buffer, isoInResult.packets[0].data.byteOffset, isoInResult.packets[0].data.byteLength).length, 2);
    assert.strictEqual(isoInResult.data.byteLength, 5, '結果全体の.dataは全パケット分を結合した長さになるはず(2+3=5)');
    console.log('isochronousTransferIn success: packets[]/combined .data が正しく組み立てられる: OK');

    // 正常系: OUT方向(endpoint 4, isochronous)
    isochronousTransferOutResponse = { success: true, packets: [{ status: 'ok', bytesWritten: 2 }, { status: 'ok', bytesWritten: 2 }] };
    const isoOutResult = await isoDev.isochronousTransferOut(4, new Uint8Array([1, 2, 3, 4]), [2, 2]);
    assert.ok(fakeBridgeCalls.some(c => c[0] === 'isochronousTransferOut' && c[2] === 4 && c[3] === 'AQIDBA==' && c[4] === JSON.stringify([2, 2])),
        'base64(1,2,3,4)=AQIDBA== がブリッジへ渡っているはず(v0.0.4a0: hexからbase64へ移行)');
    assert.strictEqual(isoOutResult.packets.length, 2);
    assert.strictEqual(isoOutResult.packets[0].bytesWritten, 2);
    console.log('isochronousTransferOut success: packets[] が正しく組み立てられる: OK');

    // 🛡️ 転送(bulk/control)の正常系はstatus:'ok'で返る。
    bulkTransferInResponse = { success: true, status: 'ok', data: 'AQL/' };
    const inResult = await dev.transferIn(1, 64);
    assert.strictEqual(inResult.status, 'ok');
    assert.strictEqual(inResult.data.byteLength, 3);
    assert.strictEqual(inResult.data.getUint8(0), 0x01);

    bulkTransferOutResponse = { success: true, status: 'ok', bytesWritten: 4 };
    const outResult = await dev.transferOut(2, new Uint8Array([1, 2, 3, 4]));
    assert.strictEqual(outResult.status, 'ok');
    assert.strictEqual(outResult.bytesWritten, 4);
    console.log('transferIn/transferOut normal transfer (status:"ok"): OK');

    // 🛡️ 実仕様(USBTransferStatus)どおり、STALLはPromiseのrejectではなく
    // status:'stall'を伴う"成功"resolveで返るべき(Python側がSTALL検出時に
    // success:trueのままstatus:'stall'を返してくる設計との対応を確認する)。
    bulkTransferInResponse = { success: true, status: 'stall', data: '' };
    const stallIn = await dev.transferIn(1, 64);
    assert.strictEqual(stallIn.status, 'stall', 'STALLはrejectではなくstatus:"stall"で返るべき');
    assert.strictEqual(stallIn.data.byteLength, 0);

    bulkTransferOutResponse = { success: true, status: 'stall', bytesWritten: 0 };
    const stallOut = await dev.transferOut(2, new Uint8Array([9]));
    assert.strictEqual(stallOut.status, 'stall');
    bulkTransferInResponse = { success: true, status: 'ok', data: 'AA==' };
    bulkTransferOutResponse = { success: true, status: 'ok', bytesWritten: 1 };
    console.log('transferIn/transferOut STALL surfaces as status:"stall" (not a rejection): OK');

    const setup = { requestType: 'vendor', recipient: 'device', request: 1, value: 0, index: 0 };
    controlTransferInResponse = { success: true, status: 'ok', data: 'qg==' };
    const ctrlIn = await dev.controlTransferIn(setup, 1);
    assert.strictEqual(ctrlIn.status, 'ok');
    assert.strictEqual(ctrlIn.data.getUint8(0), 0xaa);
    controlTransferInResponse = { success: true, status: 'stall', data: '' };
    const ctrlInStall = await dev.controlTransferIn(setup, 1);
    assert.strictEqual(ctrlInStall.status, 'stall', 'controlTransferInのSTALLもstatus:"stall"で返るべき');
    console.log('controlTransferIn: normal + STALL handling: OK');

    controlTransferOutResponse = { success: true, status: 'ok', bytesWritten: 1 };
    const ctrlOut = await dev.controlTransferOut(setup, new Uint8Array([9]));
    assert.strictEqual(ctrlOut.status, 'ok');
    controlTransferOutResponse = { success: true, status: 'stall', bytesWritten: 0 };
    const ctrlOutStall = await dev.controlTransferOut(setup, new Uint8Array([9]));
    assert.strictEqual(ctrlOutStall.status, 'stall', 'controlTransferOutのSTALLもstatus:"stall"で返るべき');
    console.log('controlTransferOut: normal + STALL handling: OK');

    // ユーザー操作なし(userActivation.isActive === false)ではrequestDeviceを拒否する
    // (filters自体は妥当なものを渡し、フィルタ検証ではなく活性化チェックのほうを狙って踏む)
    navigator.userActivation.isActive = false;
    try {
        await navigator.usb.requestDevice({ filters: [{}] });
        assert.fail('should have thrown SecurityError');
    } catch (e) {
        assert.strictEqual(e.name, 'SecurityError');
    }
    console.log('requestDevice without user activation -> SecurityError: OK');
    navigator.userActivation.isActive = true;

    // connect/disconnectイベント配送
    let connectEvents = [];
    navigator.usb.addEventListener('connect', (e) => connectEvents.push(e));
    fakeBridge.deviceConnected._emit(JSON.stringify({ vendorId: 0x9999, productId: 0x1, serialNumber: 'HOTPLUG' }));
    await new Promise(r => setTimeout(r, 5));
    assert.strictEqual(connectEvents.length, 1);
    assert.strictEqual(connectEvents[0].device.serialNumber, 'HOTPLUG');
    console.log('connect event dispatch via addEventListener: OK');

    let disconnectViaProperty = null;
    navigator.usb.ondisconnect = (e) => { disconnectViaProperty = e; };
    fakeBridge.deviceDisconnected._emit(JSON.stringify({ vendorId: 0x9999, productId: 0x1 }));
    await new Promise(r => setTimeout(r, 5));
    assert.ok(disconnectViaProperty, 'ondisconnect handler should fire');
    console.log('disconnect event dispatch via ondisconnect property: OK');

    // 🛡️ バグ修正(v0.0.4)の回帰テスト: close()は必ずhandleとframe_tokenの
    // 両方をブリッジへ渡すべき。closeDeviceはPython側で@Slot(int, str)として
    // 2引数必須で登録されているため、(修正前のように)handleだけの1引数で
    // 呼ぶと、QWebChannelはスロット呼び出しごと黙って握りつぶし、
    // closeDeviceが一切実行されない(=デバイスハンドルが永久にリークする)
    // ことを実機のQWebChannel往復で確認した実バグの回帰テスト。
    window.__pyUsbFrameToken = 'close-test-frame-token';
    const closeDev = await navigator.usb.requestDevice({ filters: [{}] });
    await closeDev.open();
    fakeBridgeCalls.length = 0;
    await closeDev.close();
    assert.strictEqual(closeDev.opened, false, 'close()後はopened=falseになるべき');
    const closeCalls = fakeBridgeCalls.filter(c => c[0] === 'closeDevice');
    assert.strictEqual(closeCalls.length, 1, 'closeDevice()がちょうど1回ブリッジへ渡されるべき');
    assert.strictEqual(closeCalls[0][1], closeDev._handle, 'closeDeviceへ渡すhandleが正しいはず');
    assert.strictEqual(closeCalls[0][2], 'close-test-frame-token',
        'closeDeviceへframe_tokenも渡されるべき(handleのみの1引数呼び出しは' +
        'QWebChannelにスロット呼び出しごと握りつぶされる実バグがあった)');
    delete window.__pyUsbFrameToken;
    console.log('close() forwards (handle, frame_token) to closeDevice -- regression test for v0.0.4 bug: OK');

    // 🛡️ frame_origin.FrameOriginTracker がPython側からwindow.__pyUsbFrameToken
    //    へ書き込んだ値が、実際に全てのブリッジ呼び出しの末尾引数として
    //    送られることを確認する(0.0.3bで実装したフレーム単位オリジン特定の
    //    中核となる契約)。未設定の場合は空文字列が送られることも確認する。
    delete window.__pyUsbFrameToken;
    fakeBridgeCalls.length = 0;
    await navigator.usb.getDevices();
    assert.strictEqual(fakeBridgeCalls[0][0], 'listDevices');
    assert.strictEqual(fakeBridgeCalls[0][1], '', 'トークン未設定時は空文字列が送られるはず');
    console.log('frame token defaults to empty string when window.__pyUsbFrameToken is unset: OK');

    window.__pyUsbFrameToken = 'test-frame-token-xyz';
    fakeBridgeCalls.length = 0;
    await navigator.usb.getDevices();
    assert.strictEqual(fakeBridgeCalls[0][0], 'listDevices');
    assert.strictEqual(fakeBridgeCalls[0][1], 'test-frame-token-xyz', 'window.__pyUsbFrameTokenの値がそのまま送られるはず');
    console.log('frame token is forwarded to the bridge when window.__pyUsbFrameToken is set: OK');
    delete window.__pyUsbFrameToken;

    // 🚚 大容量転送対応(v0.0.4a0)の回帰テスト: WebADB等が送るような大きな
    // ペイロード(ここでは500KB。旧hex実装でも壊れなかったであろう閾値より
    // 十分大きく、base64移行時にString.fromCharCode.apply()を分割せず丸ごと
    // 配列へ適用する誤実装だとRangeErrorで確実に落ちるサイズ)を実際に
    // transferOut()->transferIn()相当の往復にかけ、チャンク分割済みの
    // bytesToBase64()/base64ToUint8()がクラッシュせず、内容も欠落・破損
    // しないことを確認する。
    const bigSize = 500 * 1024;
    const bigPayload = new Uint8Array(bigSize);
    for (let i = 0; i < bigSize; i++) bigPayload[i] = i % 256;

    let capturedB64 = null;
    bulkTransferOutResponse = { success: true, status: 'ok', bytesWritten: bigSize };
    await dev.transferOut(2, bigPayload);
    const bigOutCall = fakeBridgeCalls.filter(c => c[0] === 'bulkTransferOut').pop();
    capturedB64 = bigOutCall[3];
    assert.ok(capturedB64.length > bigSize, 'base64文字列は元のバイト数より長いはず(約1.33倍)');

    // ブリッジが送り返してくる側(IN方向)も同じ大きさのデータで往復させる
    bulkTransferInResponse = { success: true, status: 'ok', data: capturedB64 };
    const bigInResult = await dev.transferIn(1, bigSize);
    const roundTripped = new Uint8Array(bigInResult.data.buffer, bigInResult.data.byteOffset, bigInResult.data.byteLength);
    assert.strictEqual(roundTripped.length, bigSize, '往復後もサイズが変わらないはず');
    let matches = true;
    for (let i = 0; i < bigSize; i++) { if (roundTripped[i] !== bigPayload[i]) { matches = false; break; } }
    assert.ok(matches, '500KB往復後もバイト列が完全一致するはず(1バイトも欠落・破損しない)');
    bulkTransferInResponse = { success: true, status: 'ok', data: 'AA==' };
    bulkTransferOutResponse = { success: true, status: 'ok', bytesWritten: 1 };
    console.log('500KB payload round-trip via chunked base64 encode/decode (WebADB-scale transfer): OK');

    // 🛡️ バグ修正(v0.0.4b2)の回帰テスト: Python側(errors.py)が返す
    // "IndexSizeError:"/"DataError:"/"NotFoundError:"/"InvalidAccessError:" 接頭辞つき
    // エラーが、throwFromResult()のKNOWN_ERROR_PREFIXESに含まれておらず、正しい
    // DOMException名へ振り分けられていなかった(=常定のNetworkErrorになり、かつ
    // メッセージ本文に接頭辞がそのまま残ってしまっていた)実バグの回帰テスト。
    // bulkTransferInにはJS側の事前チェックが一切無い(直接ブリッジへ問い合わせる)
    // ため、このパスはPythonが返すエラー名に完全に依存する。
    const errorPrefixCases = [
        ['IndexSizeError:', 'endpoint number 99 is out of range (must be between 0 and 15)'],
        ['DataError:', 'length 999999999 is out of range (must be between 0 and 33554432)'],
        ['NotFoundError:', 'no such interface'],
        ['InvalidAccessError:', 'endpoint 3 is a isochronous endpoint, not bulk or interrupt'],
    ];
    for (const [prefix, msg] of errorPrefixCases) {
        bulkTransferInResponse = { success: false, error: prefix + ' ' + msg };
        let caught = null;
        try {
            await dev.transferIn(1, 4);
        } catch (e) {
            caught = e;
        }
        const expectedName = prefix.slice(0, -1);
        assert.ok(caught instanceof DOMException, `${prefix}: DOMExceptionが投げられるはず`);
        assert.strictEqual(caught.name, expectedName,
            `${prefix}: DOMException.nameは'${expectedName}'であるべき(実際: '${caught.name}') -- ` +
            `旧実装ではKNOWN_ERROR_PREFIXESに無いプレフィックスは全てNetworkErrorになっていた`);
        assert.strictEqual(caught.message, msg,
            `${prefix}: DOMException.messageから接頭辞が正しく取り除かれているべき(実際: '${caught.message}') -- ` +
            `旧実装では"${prefix} "がメッセージ本文にそのまま残ってしまっていた`);
    }
    bulkTransferInResponse = { success: true, status: 'ok', data: 'AA==' };
    console.log('Python error prefixes (IndexSizeError/DataError/NotFoundError/InvalidAccessError) dispatch to the correct DOMException.name: OK');

    // 🔧 v0.0.4b2: window.__pysideWebUSB (F12/DevTools向けデバッグネームスペース) の検証
    assert.strictEqual(typeof window.__pysideWebUSB, 'object', 'window.__pysideWebUSBが生えているはず');
    assert.strictEqual(typeof window.__pysideWebUSB.listGrantedDevices, 'function');
    assert.strictEqual(typeof window.__pysideWebUSB.bridgeInfo, 'function');
    assert.strictEqual(typeof window.__pysideWebUSB.explainTransferLimits, 'function');

    const grantedRows = await window.__pysideWebUSB.listGrantedDevices();
    assert.ok(Array.isArray(grantedRows));
    assert.strictEqual(grantedRows.length, fakeDevices.length);
    assert.strictEqual(grantedRows[0].vendorId, '0x' + fakeDevices[0].vendorId.toString(16));
    // 🛡️ 安全設計の確認: listGrantedDevices()はnavigator.usb.getDevices()と
    // 完全に同じデータであり、それ以上の情報(他オリジンの許可済みデバイス等)を
    // 一切含まないこと。
    const viaGetDevices = await navigator.usb.getDevices();
    assert.strictEqual(grantedRows.length, viaGetDevices.length,
        'listGrantedDevices()はgetDevices()と同じデータ量であるべき(それ以上の開示は無い)');

    const info = await window.__pysideWebUSB.bridgeInfo();
    assert.strictEqual(info.bridgeVersion, '0.0.4b2-test');
    assert.strictEqual(info.rustAccelerated, true);
    assert.strictEqual(info.transferLimits.hostSafetyHardLimit, 536870912);

    const limits = await window.__pysideWebUSB.explainTransferLimits();
    assert.strictEqual(limits.chromeCompatibleWarnThreshold, 33554432);
    console.log('window.__pysideWebUSB debug namespace (listGrantedDevices/bridgeInfo/explainTransferLimits): OK');

    console.log('ALL WEBUSB POLYFILL JS TESTS PASSED');
}
main().catch((e) => { console.error('TEST FAILED:', e); process.exit(1); });
