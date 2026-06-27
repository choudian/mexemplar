import { Search } from "lucide-react";

export function SearchInput({
  value,
  onChange,
  ariaLabel,
  placeholder,
  iconSize = 14,
}: {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  iconSize?: number;
}): JSX.Element {
  return (
    <>
      <Search size={iconSize} />
      <input
        aria-label={ariaLabel}
        onChange={(event) => onChange(event.currentTarget.value)}
        placeholder={placeholder}
        value={value}
      />
    </>
  );
}

export default SearchInput;
