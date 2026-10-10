import type { ProfileFieldConfig } from "@/lib/profileFields";

interface ProfileFieldInputProps {
  field: ProfileFieldConfig;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}

export default function ProfileFieldInput({ field, value, error, onChange }: ProfileFieldInputProps) {
  const id = `profile-${field.key}`;
  const messageId = `${id}-message`;
  const inputClass = `mt-2 h-[42px] w-full rounded-[10px] border bg-white px-3 text-[14px] text-[#181a20] outline-none focus:border-[#4f6ef7] ${
    error ? "border-[#c53030]" : "border-[#e5e7eb]"
  }`;
  const message = error ?? field.hint;

  return (
    <div>
      <label htmlFor={id} className="text-[13px] font-semibold text-[#181a20]">
        {field.label}
      </label>
      {field.kind === "select" ? (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={message ? messageId : undefined}
          className={inputClass}
        >
          {field.allowEmpty !== false && <option value="">선택 안 함</option>}
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <div className="relative">
          <input
            id={id}
            type={field.kind}
            inputMode={field.kind === "number" ? "decimal" : undefined}
            value={value}
            min={field.min}
            max={field.max}
            step={field.step}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={message ? messageId : undefined}
            className={`${inputClass} ${field.unit ? "pr-12" : ""}`}
          />
          {field.unit && (
            <span className="pointer-events-none absolute right-3 top-[29px] -translate-y-1/2 text-[13px] text-[#667085]">
              {field.unit}
            </span>
          )}
        </div>
      )}
      {message && (
        <p id={messageId} className={`mt-1 text-[12px] leading-5 ${error ? "text-[#c53030]" : "text-[#667085]"}`}>
          {message}
        </p>
      )}
    </div>
  );
}
