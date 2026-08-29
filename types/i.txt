// このファイルはREADME.mdの「TypeScript」節で説明している検証の実体です。
// 各行が実際にコンパイルエラーになる(=型が制約として機能している)ことを
// `tsc --strict --noEmit webusb-polyfill.d.ts negative-check.ts` の終了コード0で
// 確認しています(@ts-expect-errorが「期待通りエラーになった」ことの確認なので、
// 成功時の終了コードは0になります)。

// 型が実際に制約として機能しているかの否定的検証(コンパイルエラーになるべき箇所)。
async function bad(device: USBDevice) {
    // @ts-expect-error: 'babble'は仕様のUSBTransferStatusに存在しない誤字
    const s: USBTransferStatus = 'overflow';
    // @ts-expect-error: directionは'in'|'out'のみ、'inout'は無効
    await device.clearHalt('inout', 1);
    // @ts-expect-error: vendorIdは number、文字列は無効
    await navigator.usb.requestDevice({ filters: [{ vendorId: '0x18d1' }] });
}
