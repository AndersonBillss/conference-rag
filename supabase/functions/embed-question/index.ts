import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const JSON_HEADERS = { "Content-Type": "application/json" };
const GITHUB_PAGES_ORIGIN = "https://andersonbillss.github.io";

function corsHeaders(origin: string | null): Record<string, string> {
  let allowedOrigin = "null";
  if (origin === GITHUB_PAGES_ORIGIN) {
    allowedOrigin = origin;
  } else if (origin) {
    try {
      const url = new URL(origin);
      if ((url.protocol === "http:" || url.protocol === "https:") &&
        (url.hostname === "localhost" || url.hostname === "127.0.0.1")) {
        allowedOrigin = origin;
      }
    } catch {
      // Keep the origin disallowed when it is not a valid URL.
    }
  }

  return {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

function isAuthenticatedUser(authorization: string | null): boolean {
  if (!authorization?.startsWith("Bearer ")) return false;

  const token = authorization.slice("Bearer ".length);
  const payloadPart = token.split(".")[1];
  if (!payloadPart) return false;

  try {
    const base64 = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64));
    return payload.role === "authenticated" && typeof payload.sub === "string";
  } catch {
    return false;
  }
}

function jsonResponse(
  body: Record<string, unknown>,
  status: number,
  cors: Record<string, string>,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, ...JSON_HEADERS },
  });
}

Deno.serve(async (req: Request) => {
  const cors = corsHeaders(req.headers.get("origin"));

  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: cors });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405, cors);
  }

  // The gateway verifies the JWT signature. This additionally rejects valid
  // anonymous-key JWTs, so only signed-in Supabase users can call OpenAI.
  if (!isAuthenticatedUser(req.headers.get("authorization"))) {
    return jsonResponse({ error: "Authentication required" }, 401, cors);
  }

  const apiKey = Deno.env.get("OPENAI_API_KEY");
  if (!apiKey) {
    console.error("OPENAI_API_KEY is not configured for this function");
    return jsonResponse({ error: "Embedding service is not configured" }, 500, cors);
  }

  let question: unknown;
  try {
    const body = await req.json();
    question = body?.question;
  } catch {
    return jsonResponse({ error: "Request body must be valid JSON" }, 400, cors);
  }

  if (typeof question !== "string" || question.trim().length === 0) {
    return jsonResponse({ error: "A non-empty question is required" }, 400, cors);
  }
  if (question.length > 8000) {
    return jsonResponse({ error: "Question is too long" }, 400, cors);
  }

  try {
    const openAiResponse = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: question.trim(),
      }),
      signal: AbortSignal.timeout(30_000),
    });

    if (!openAiResponse.ok) {
      console.error(`OpenAI embeddings request failed with status ${openAiResponse.status}`);
      return jsonResponse({ error: "Could not create an embedding" }, 502, cors);
    }

    const result = await openAiResponse.json();
    const embedding = result?.data?.[0]?.embedding;
    if (!Array.isArray(embedding) || embedding.length !== 1536) {
      console.error("OpenAI returned an unexpected embedding format");
      return jsonResponse({ error: "Embedding service returned an invalid response" }, 502, cors);
    }

    return jsonResponse({ embedding }, 200, cors);
  } catch (error) {
    console.error("Embedding request failed", error);
    return jsonResponse({ error: "Could not create an embedding" }, 502, cors);
  }
});
