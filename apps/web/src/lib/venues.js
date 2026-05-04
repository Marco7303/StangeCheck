import { querySupabase } from "./supabase";
import { listBeerSpots } from "./mockDb";

function toUiVenue(row) {
  const price = Number(row.cheapest_lager_price_chf);
  const hasPrice = Number.isFinite(price);
  const evidence =
    typeof row.website_price_evidence === "string" &&
    row.website_price_evidence.trim()
      ? row.website_price_evidence
      : null;

  return {
    id: row.id,
    name: row.name ?? "Unnamed venue",
    city: row.city ?? "Unknown city",
    canton: row.canton ?? "CH",
    address: row.address ?? "Address unavailable",
    lat: Number(row.lat),
    lng: Number(row.lng),
    price: hasPrice ? price : null,
    beer: row.cheapest_lager_name ?? "Lager price pending",
    vibe: evidence,
    website: row.website ?? "",
    source: row.price_source ?? row.source ?? "",
    priceUpdatedAt: row.price_updated_at ?? null,
    userFlagged: row.user_flagged === true,
  };
}

function hasSupabaseBrowserConfig() {
  return (
    Boolean(import.meta.env.VITE_SUPABASE_URL) &&
    Boolean(import.meta.env.VITE_SUPABASE_ANON_KEY)
  );
}

export async function listVenues() {
  if (!hasSupabaseBrowserConfig()) {
    return listBeerSpots();
  }

  const params = new URLSearchParams({
    select: [
      "id",
      "name",
      "city",
      "canton",
      "address",
      "lat",
      "lng",
      "website",
      "source",
      "cheapest_lager_name",
      "cheapest_lager_price_chf",
      "price_source",
      "price_updated_at",
      "user_flagged",
    ].join(","),
    "lat": "not.is.null",
    "lng": "not.is.null",
    "cheapest_lager_price_chf": "not.is.null",
    order: "name.asc",
  });

  try {
    const rows = await querySupabase(`venues?${params.toString()}`);
    return rows.map(toUiVenue);
  } catch (error) {
    console.warn("Supabase venue fetch failed, falling back to mock data.", error);
    return listBeerSpots();
  }
}

export async function flagVenuePrice(venueId) {
  if (!hasSupabaseBrowserConfig()) {
    throw new Error("Supabase setup required to flag a price.");
  }

  const rows = await querySupabase(`venues?id=eq.${encodeURIComponent(venueId)}&select=id,user_flagged`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({
      user_flagged: true,
    }),
  });

  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(
      "Supabase did not update the row. This is usually caused by a missing UPDATE policy on venues.",
    );
  }
}
