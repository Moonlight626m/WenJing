export const INPUT_CLASS =
  "rounded-lg border border-zinc-300 bg-transparent px-3 py-2 outline-none focus:border-blue-400 dark:border-zinc-700";

export const SUBMIT_CLASS =
  "rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50 dark:bg-zinc-100 dark:text-black";

interface AuthFieldProps {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
}

/** 账号表单的受控输入（label + input），统一样式。 */
export function AuthField({
  label,
  name,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
  minLength,
  maxLength,
}: AuthFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
      <input
        name={name}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        className={INPUT_CLASS}
      />
    </label>
  );
}
