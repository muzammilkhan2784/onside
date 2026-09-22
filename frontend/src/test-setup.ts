import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off, so Testing Library's automatic cleanup does not run.
// Without this the DOM accumulates across tests and queries find duplicates.
afterEach(cleanup);
