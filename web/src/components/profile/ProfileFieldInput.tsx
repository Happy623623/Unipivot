import type { FieldDetails, ProfileFieldConfig } from "@/lib/profileFields";

interface ProfileFieldInputProps {
  field: ProfileFieldConfig;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}

// 칸 아래 펼치는 설명(기준 중위소득 등). 브라우저의 펼치기(details)라 키보드·화면 읽기 프로그램이 그대로 쓴다
function FieldDetailsView({ details }: { details: FieldDetails }) {
  return (
    <details className="mt-1 text-[12px] leading-5 text-[#475467]">
      <summary className="cursor-pointer font-semibold text-[#4f6ef7]">{details.summary}</summary>
      <div className="mt-2 flex flex-col gap-2 rounded-[10px] bg-[#f7f8fa] p-3">
        {details.before.map((text) => (
          <p key={text}>{text}</p>
        ))}
        {details.table && (
          <table className="w-full max-w-[280px] text-left">
            <caption className="pb-1 text-left font-semibold text-[#344054]">{details.table.caption}</caption>
            <thead>
              <tr>
                <th scope="col" className="py-0.5 font-medium text-[#667085]">{details.table.head[0]}</th>
                <th scope="col" className="py-0.5 text-right font-medium text-[#667085]">{details.table.head[1]}</th>
              </tr>
            </thead>
            <tbody>
              {details.table.rows.map(([name, value]) => (
                <tr key={name}>
                  <th scope="row" className="py-0.5 font-normal">{name}</th>
                  <td className="py-0.5 text-right tabular-nums">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {details.after.map((text) => (
          <p key={text}>{text}</p>
        ))}
      </div>
    </details>
  );
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
            maxLength={field.maxLength}
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
      {field.details && <FieldDetailsView details={field.details} />}
    </div>
  );
}
