export async function api<T>(path: string, data?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data, (key, value: unknown) => {
            if (typeof value === "number" && !Number.isFinite(value))
              throw new Error(`Numeric field '${key}' is empty or not finite.`);
            return value;
          }),
        },
  );
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    const detail: unknown = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .slice(0, 8)
              .map(
                (item: { loc?: (string | number)[]; msg?: string }) =>
                  `${item.loc?.filter((v) => v !== "body").join(".") ?? "Input"}: ${item.msg ?? "Invalid value"}`,
              )
              .join("; ")
          : "The request could not be completed. Check the input values.",
    );
  }
  return response.json() as Promise<T>;
}
export const utc = (s: string) =>
  new Date(s).toISOString().replace("T", " ").slice(0, 19) + " UTC";
export const duration = (s: number) => {
  const minutes = Math.round(s / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};

export function downloadJson(filename: string, value: unknown) {
  const payload = JSON.stringify(value, null, 2);
  if (payload === undefined) throw new Error("No JSON content to export");
  const url = URL.createObjectURL(
    new Blob([payload + "\n"], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
