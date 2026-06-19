import { describe, it, expect } from "vitest";
import { isTransient, retry } from "./retry";

describe("isTransient", () => {
  it("treats raw fetch failures (TypeError) as transient", () => {
    expect(isTransient(new TypeError("Failed to fetch"))).toBe(true);
  });

  it("treats connection/5xx codes as transient", () => {
    expect(isTransient({ code: "57P03" })).toBe(true); // server starting up
    expect(isTransient({ code: "503" })).toBe(true);
  });

  it("treats real query errors as NOT transient", () => {
    // Missing FK relationship — PostgREST PGRST200; should fail fast.
    expect(isTransient({ code: "PGRST200", message: "Could not find a relationship" })).toBe(false);
    expect(isTransient({ code: "42501", message: "permission denied" })).toBe(false);
    expect(isTransient(null)).toBe(false);
  });
});

describe("retry", () => {
  it("returns immediately on success", async () => {
    let calls = 0;
    const out = await retry(async () => { calls++; return "ok"; });
    expect(out).toBe("ok");
    expect(calls).toBe(1);
  });

  it("retries transient failures then succeeds", async () => {
    let calls = 0;
    const out = await retry(
      async () => {
        calls++;
        if (calls < 3) throw new TypeError("Failed to fetch");
        return "ok";
      },
      { attempts: 3, baseDelayMs: 1 },
    );
    expect(out).toBe("ok");
    expect(calls).toBe(3);
  });

  it("does NOT retry a non-transient error", async () => {
    let calls = 0;
    await expect(
      retry(async () => { calls++; throw { code: "42501", message: "permission denied" }; },
        { attempts: 3, baseDelayMs: 1 }),
    ).rejects.toMatchObject({ code: "42501" });
    expect(calls).toBe(1);
  });

  it("gives up after the attempt budget and throws the last error", async () => {
    let calls = 0;
    await expect(
      retry(async () => { calls++; throw new TypeError("Failed to fetch"); },
        { attempts: 2, baseDelayMs: 1 }),
    ).rejects.toBeInstanceOf(TypeError);
    expect(calls).toBe(2);
  });
});
