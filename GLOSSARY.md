# Glossary

Words we use the same way everywhere: code, docs, chat. No implementation here, just meaning.

- **Listing**: one batch of salvaged material for sale (a material, a quantity, a price, a place, a seller).
- **Detection**: what the AI claims is in a photo (a material, a confidence, a quantity estimate). A detection becomes a listing only when a contractor confirms it.
- **Share**: a detection's slice of the photo's total confidence, as a percent. Shares in one photo always add to 100.
- **Coverage**: how much of the photo a material fills (0 to 1). Quantities are computed from coverage, never guessed.
- **Non-construction**: anything the AI saw that can never be listed (people, clothes, pets, food, plastic trash). Shown in the UI so the exclusion is visible, not silent.
- **Site verdict**: the AI's answer to "is this a demolition or construction scene at all?" A bedsheet photo gets a no.
- **Source**: the trail of which passes agreed on a detection (for example World plus the color pass). Shown per detection so a wrong result can be traced.
- **Fallback**: the low-confidence Concrete guess used only when the frame looks like construction but no pass fired. Always labeled as a guess, never stated as fact.
- **Match score**: how well a listing fits a buyer's need (0–100), from material, quantity, distance, and condition.
- **Request**: a buyer's ask for a listing's material. Starts pending; the contractor accepts or declines. No money moves. Handshake only.
- **Impact**: running totals of waste diverted (tonnes) and value recovered (rupees).
- **Prompt**: a descriptive phrase given to the open-vocabulary detector (for example "a stack of red clay bricks"). Phrasing decides what gets boxed.
- **Hard negative**: a phrase for something that looks like material but isn't salvage (a painted wall, a ceiling). Detected, then thrown away.
- **Gate**: the CLIP check each candidate box must pass ("construction or household?"). Weak boxes below the gate are rejected openly.
- **Seed**: the starter listings loaded on first run so search and matching work before anyone uploads.
