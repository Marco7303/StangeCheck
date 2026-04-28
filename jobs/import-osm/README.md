# import-osm

This job is a placeholder for the future OSM to Supabase import pipeline.

Later it will:

- query Overpass for Zug venues
- filter `amenity=pub`, `bar`, `food_court`, `biergarten`, `nightclub`
- include `brewery=*` venues
- validate and normalize venue records
- upsert valid venues into Supabase
