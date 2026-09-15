/** 账号表单错误提示（按错误码/信息展示，服务端 envelope 经 formatApiError）。 */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-300">
      {message}
    </p>
  );
}
