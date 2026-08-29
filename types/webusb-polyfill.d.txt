// Type definitions for the pyside6-webusb JS polyfill (navigator.usb)
// Project: https://github.com/steck0714/Mock-webusb
//
// このファイルは pyside6-webusb (src/pyside6_webusb/polyfill.py) が
// `navigator.usb` としてインストールするポリフィルの型を、WICG/webusb の
// 公式 WebIDL (https://github.com/WICG/webusb/blob/main/index.bs) から直接
// 書き起こしたものです。ハルシネーションを避けるため、独自の記憶からではなく
// 実際に取得した index.bs の `<xmp class="idl">` ブロックを一つずつ転記して
// 作成しています。
//
// 使い方: このファイルをTypeScriptプロジェクトへコピーし、tsconfig.jsonの
// "include" に含めてください(このパッケージはPyPI配布のPythonパッケージで
// あり、npm経由でのインストールは想定していないため、`node_modules` 経由の
// 自動解決ではなく、ファイルを直接コピーする運用を想定しています)。
//
//   cp node_modules_ではなく実ファイルをコピー/webusb-polyfill.d.ts ./src/types/
//
// または、このリポジトリを(サブモジュール等で)フロントエンド側と同じ
// チェックアウトに置いているなら、三重スラッシュ参照でも構いません:
//
//   /// <reference path="../../pyside6-webusb/types/webusb-polyfill.d.ts" />
//
// 注意: これは実ブラウザ純正のWebUSB型ではなく、pyside6-webusbのポリフィル
// (QtWebEngine上でPySide6アプリが提供する実装)向けです。ほぼ全ての面で
// 実仕様と型的に同一になるよう作成していますが、polyfill.py/bridge.pyの
// 挙動上の既知の単純化(DOMExceptionの名前が一部の異常系でSpecと完全一致
// しない場合がある等)についてはREADME.md「Spec compliance notes」と
// CHANGELOG.mdを参照してください(型定義そのものには影響しません — 例外は
// どの名前であってもcatch (e)で受けられます)。
//
// バージョン対応: pyside6-webusb v0.0.4a0 時点のUSBDevice実装(babbleステータス
// 対応後)を反映しています。

export {};

declare global {
  // ============================================================
  // navigator.usb / worker.navigator.usb
  // ============================================================
  interface Navigator {
    readonly usb: USB;
  }
  interface WorkerNavigator {
    readonly usb: USB;
  }

  interface USBEventMap {
    connect: USBConnectionEvent;
    disconnect: USBConnectionEvent;
  }

  interface USB extends EventTarget {
    onconnect: ((this: USB, ev: USBConnectionEvent) => any) | null;
    ondisconnect: ((this: USB, ev: USBConnectionEvent) => any) | null;

    getDevices(): Promise<USBDevice[]>;
    requestDevice(options: USBDeviceRequestOptions): Promise<USBDevice>;

    addEventListener<K extends keyof USBEventMap>(
      type: K,
      listener: (this: USB, ev: USBEventMap[K]) => any,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions
    ): void;
    removeEventListener<K extends keyof USBEventMap>(
      type: K,
      listener: (this: USB, ev: USBEventMap[K]) => any,
      options?: boolean | EventListenerOptions
    ): void;
    removeEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | EventListenerOptions
    ): void;
  }

  // ============================================================
  // Device selection (USBDeviceFilter / USBDeviceRequestOptions)
  // ============================================================
  interface USBDeviceFilter {
    vendorId?: number;
    productId?: number;
    classCode?: number;
    subclassCode?: number;
    protocolCode?: number;
    serialNumber?: string;
  }

  interface USBDeviceRequestOptions {
    filters: USBDeviceFilter[];
    /** 既定値は仕様どおり空配列 `[]`(=exclusionFiltersなし)。 */
    exclusionFilters?: USBDeviceFilter[];
  }

  // ============================================================
  // Connection events (USB.onconnect / .ondisconnect)
  // ============================================================
  interface USBConnectionEventInit extends EventInit {
    device: USBDevice;
  }

  class USBConnectionEvent extends Event {
    constructor(type: string, eventInitDict: USBConnectionEventInit);
    readonly device: USBDevice;
  }

  // ============================================================
  // Transfer results (USBTransferStatus / *TransferResult / *TransferPacket)
  // ============================================================
  type USBTransferStatus = "ok" | "stall" | "babble";

  class USBInTransferResult {
    constructor(status: USBTransferStatus, data?: DataView | null);
    readonly data: DataView | null;
    readonly status: USBTransferStatus;
  }

  class USBOutTransferResult {
    constructor(status: USBTransferStatus, bytesWritten?: number);
    readonly bytesWritten: number;
    readonly status: USBTransferStatus;
  }

  class USBIsochronousInTransferPacket {
    constructor(status: USBTransferStatus, data?: DataView | null);
    readonly data: DataView | null;
    readonly status: USBTransferStatus;
  }

  class USBIsochronousInTransferResult {
    constructor(packets: USBIsochronousInTransferPacket[], data?: DataView | null);
    readonly data: DataView | null;
    readonly packets: ReadonlyArray<USBIsochronousInTransferPacket>;
  }

  class USBIsochronousOutTransferPacket {
    constructor(status: USBTransferStatus, bytesWritten?: number);
    readonly bytesWritten: number;
    readonly status: USBTransferStatus;
  }

  class USBIsochronousOutTransferResult {
    constructor(packets: USBIsochronousOutTransferPacket[]);
    readonly packets: ReadonlyArray<USBIsochronousOutTransferPacket>;
  }

  // ============================================================
  // Control transfers (USBControlTransferParameters / USBRequestType / USBRecipient)
  // ============================================================
  type USBRequestType = "standard" | "class" | "vendor";
  type USBRecipient = "device" | "interface" | "endpoint" | "other";

  interface USBControlTransferParameters {
    requestType: USBRequestType;
    recipient: USBRecipient;
    request: number;
    value: number;
    index: number;
  }

  // ============================================================
  // Endpoints (USBDirection / USBEndpointType / USBEndpoint)
  // ============================================================
  type USBDirection = "in" | "out";
  type USBEndpointType = "bulk" | "interrupt" | "isochronous";

  class USBEndpoint {
    constructor(alternate: USBAlternateInterface, endpointNumber: number, direction: USBDirection);
    readonly endpointNumber: number;
    readonly direction: USBDirection;
    readonly type: USBEndpointType;
    readonly packetSize: number;
  }

  // ============================================================
  // Interfaces / alternates / configurations
  // ============================================================
  class USBAlternateInterface {
    constructor(deviceInterface: USBInterface, alternateSetting: number);
    readonly alternateSetting: number;
    readonly interfaceClass: number;
    readonly interfaceSubclass: number;
    readonly interfaceProtocol: number;
    readonly interfaceName: string | null;
    readonly endpoints: ReadonlyArray<USBEndpoint>;
  }

  class USBInterface {
    constructor(configuration: USBConfiguration, interfaceNumber: number);
    readonly interfaceNumber: number;
    readonly alternate: USBAlternateInterface;
    readonly alternates: ReadonlyArray<USBAlternateInterface>;
    readonly claimed: boolean;
  }

  class USBConfiguration {
    constructor(device: USBDevice, configurationValue: number);
    readonly configurationValue: number;
    readonly configurationName: string | null;
    readonly interfaces: ReadonlyArray<USBInterface>;
  }

  // ============================================================
  // USBDevice -- the main interface
  // ============================================================
  class USBDevice {
    readonly usbVersionMajor: number;
    readonly usbVersionMinor: number;
    readonly usbVersionSubminor: number;
    readonly deviceClass: number;
    readonly deviceSubclass: number;
    readonly deviceProtocol: number;
    readonly vendorId: number;
    readonly productId: number;
    readonly deviceVersionMajor: number;
    readonly deviceVersionMinor: number;
    readonly deviceVersionSubminor: number;
    readonly manufacturerName: string | null;
    readonly productName: string | null;
    readonly serialNumber: string | null;
    readonly configuration: USBConfiguration | null;
    readonly configurations: ReadonlyArray<USBConfiguration>;
    readonly opened: boolean;

    open(): Promise<void>;
    close(): Promise<void>;
    /** ページが自発的に、この端末への許可を取り消す(仕様どおり)。 */
    forget(): Promise<void>;

    selectConfiguration(configurationValue: number): Promise<void>;
    claimInterface(interfaceNumber: number): Promise<void>;
    releaseInterface(interfaceNumber: number): Promise<void>;
    selectAlternateInterface(interfaceNumber: number, alternateSetting: number): Promise<void>;

    controlTransferIn(setup: USBControlTransferParameters, length: number): Promise<USBInTransferResult>;
    controlTransferOut(setup: USBControlTransferParameters, data?: BufferSource): Promise<USBOutTransferResult>;

    clearHalt(direction: USBDirection, endpointNumber: number): Promise<void>;

    transferIn(endpointNumber: number, length: number): Promise<USBInTransferResult>;
    transferOut(endpointNumber: number, data: BufferSource): Promise<USBOutTransferResult>;

    isochronousTransferIn(
      endpointNumber: number,
      packetLengths: number[]
    ): Promise<USBIsochronousInTransferResult>;
    isochronousTransferOut(
      endpointNumber: number,
      data: BufferSource,
      packetLengths: number[]
    ): Promise<USBIsochronousOutTransferResult>;

    reset(): Promise<void>;
  }
}
