const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

function buildHeaders() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      "Supabase setup required. Add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to your .env.",
    );
  }

  return {
    apikey: supabaseAnonKey,
    Authorization: `Bearer ${supabaseAnonKey}`,
  };
}

export async function querySupabase(path, init = {}) {
  const response = await fetch(`${supabaseUrl}/rest/v1/${path}`, {
    ...init,
    headers: {
      ...buildHeaders(),
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Supabase request failed with ${response.status}.`);
  }

  return response.json();
}
