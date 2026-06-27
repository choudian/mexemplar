import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import SearchInput from "../../src/components/SearchInput";

describe("SearchInput", () => {
  test("renders input bound to value, aria-label and placeholder", () => {
    render(
      <SearchInput
        ariaLabel="搜索工具"
        onChange={() => {}}
        placeholder="搜索工具"
        value="abc"
      />,
    );
    const input = screen.getByLabelText("搜索工具");
    expect(input).toHaveValue("abc");
    expect(input).toHaveAttribute("placeholder", "搜索工具");
  });

  test("forwards current input value on change", () => {
    const onChange = vi.fn();
    render(<SearchInput ariaLabel="搜索工具" onChange={onChange} value="" />);
    fireEvent.change(screen.getByLabelText("搜索工具"), { target: { value: "x" } });
    expect(onChange).toHaveBeenCalledWith("x");
  });

  test("omits placeholder when not provided", () => {
    render(<SearchInput ariaLabel="搜索工具" onChange={() => {}} value="" />);
    const input = screen.getByLabelText("搜索工具");
    expect(input).not.toHaveAttribute("placeholder");
  });
});
