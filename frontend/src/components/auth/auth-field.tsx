import { controlClass } from "@/components/ui/field";

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
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-ink-soft">{label}</span>
      <input
        name={name}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        className={controlClass("md", "w-full")}
      />
    </label>
  );
}
