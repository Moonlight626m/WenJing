/** 输入法选词时的回车是「上屏」不是发送。Safari 在 keydown 时 isComposing 已复位，
 * 只能再看一眼 keyCode 229。 */
export function isImeEnter(e: {
  nativeEvent: { isComposing: boolean };
  keyCode: number;
}): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}
