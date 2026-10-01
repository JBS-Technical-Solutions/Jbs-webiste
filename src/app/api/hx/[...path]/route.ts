import type { NextRequest } from "next/server";

const BACKEND_URL = (process.env.HX_API_URL || "http://localhost:8000").replace(/\/$/, "");
const BACKEND_KEY = process.env.HX_API_KEY;
const ALLOWED = new Set(["health", "info", "predict", "compare"]);

async function proxy(req: NextRequest, { params }: RouteContext<"/api/hx/[...path]">) {
  const { path } = await params;
  const endpoint = path.join("/");
  if (!ALLOWED.has(endpoint)) return Response.json({ detail: "Not found" }, { status: 404 });

  try {
    const res = await fetch(`${BACKEND_URL}/${endpoint}`, {
      method: req.method,
      headers: { "Content-Type": "application/json", ...(BACKEND_KEY && { "X-API-Key": BACKEND_KEY }) },
      body: req.method === "POST" ? await req.text() : undefined,
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "Heat exchanger backend is offline" }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST };
