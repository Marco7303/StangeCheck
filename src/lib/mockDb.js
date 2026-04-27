import { beerSpots } from "../data/beerSpots";

const simulatedLatency = 180;

export async function listBeerSpots() {
  await new Promise((resolve) => {
    window.setTimeout(resolve, simulatedLatency);
  });

  return [...beerSpots];
}
