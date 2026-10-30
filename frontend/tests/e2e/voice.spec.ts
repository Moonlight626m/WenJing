/**
 * 语音输入的权限与回退（#64）端到端。
 *
 * 覆盖「隐私/权限合规」与「失败可回退键盘」两条验收里**能脱离浏览器断言**的部分：
 * 各种 `getUserMedia` 失败都映射成可读中文，且不吞掉异常语义；录音能力探测在
 * 无 `MediaRecorder` 的环境下如实报 false（前端据此不显示按钮，而不是点了才报错）。
 *
 * 前置：无（纯函数断言，不起浏览器/服务端）。
 */
import { expect, test } from "@playwright/test";

import { hintForError, isRecordingSupported } from "../../src/lib/use-recorder";

function domError(name: string): Error {
  const err = new Error("boom");
  err.name = name;
  return err;
}

test.describe("#64 录音权限与回退", () => {
  test("权限被拒给出可执行的中文提示（而不是英文 DOMException）", () => {
    const hint = hintForError(domError("NotAllowedError"));
    expect(hint).toContain("权限");
    expect(hint).toContain("键盘输入");
    expect(hint).not.toContain("NotAllowedError");
  });

  test("没有麦克风设备时提示改用键盘", () => {
    expect(hintForError(domError("NotFoundError"))).toContain("键盘输入");
  });

  test("设备被占用与非安全上下文各有专门提示", () => {
    expect(hintForError(domError("NotReadableError"))).toContain("占用");
    expect(hintForError(domError("SecurityError"))).toContain("HTTPS");
  });

  test("未知失败仍给一条兜底提示，绝不把异常原样抛到界面", () => {
    const hint = hintForError(new Error("some internal failure"));
    expect(hint).toBe("录音失败，请改用键盘输入。");
  });

  test("非 Error 的抛出物也不炸", () => {
    expect(hintForError(null)).toContain("键盘输入");
    expect(hintForError("字符串")).toContain("键盘输入");
  });

  test("Node 环境没有 MediaRecorder：探测如实返回 false", () => {
    // 这条断言的价值在于"如实"——探测写错成恒真，UI 就会显示一个点了必报错的按钮
    expect(isRecordingSupported()).toBe(false);
  });
});
