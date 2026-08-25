import "@testing-library/jest-dom/vitest";

Object.defineProperty(Element.prototype, "scrollIntoView", {
  value: vi.fn(),
  writable: true,
});
