import { useRef } from "react";

type Props = {
  id?: string;
  value: string;
  onChange: (isoDate: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
};

export function DateInput({
  id,
  value,
  onChange,
  min,
  max,
  disabled,
  className = "",
  "aria-label": ariaLabel,
}: Props) {
  const ref = useRef<HTMLInputElement>(null);

  const openPicker = () => {
    const el = ref.current;
    if (!el || disabled) return;
    if (typeof el.showPicker === "function") {
      try {
        el.showPicker();
      } catch {
        el.focus();
      }
    } else {
      el.focus();
    }
  };

  return (
    <span className={`date-input-wrap${className ? ` ${className}` : ""}`}>
      <input
        ref={ref}
        id={id}
        type="date"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        aria-label={ariaLabel}
        className="input-date"
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="date-input-calendar"
        disabled={disabled}
        title="打开日历"
        aria-label="打开日期选择器"
        onClick={openPicker}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden fill="none">
          <path
            d="M8 2v3M16 2v3M4 9h16M5 5h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </span>
  );
}
