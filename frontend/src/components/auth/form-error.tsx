/** 账号表单错误提示（按错误码/信息展示，服务端 envelope 经 formatApiError）。 */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="measure rounded-md border border-danger/50 bg-danger-wash px-3 py-2 text-xs text-danger"
    >
      {message}
    </p>
  );
}
