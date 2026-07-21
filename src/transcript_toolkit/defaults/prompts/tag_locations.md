# Location Tagging Instructions

You are given a short contiguous passage from an oral history interview transcript (a "clip"). Your task is to determine whether that clip is relevant to a geographic place (or places) and, if it is, to return those place(s).

Note that:
- Clips may be relevant to one, none, or multiple places.
- Place can refer to a formally designated neighborhood, city, state, country, or region.
- Places may also be inferred from references to things like governments, regimes, landmarks, natural features, or institutions in those places. For example, someone might reference the political leader of a country, a university in a city, or a famous street in a neighborhood.

## Determining whether a place is substantively relevant

I want you to be very selective in applying location tags. Only tag a clip to a location when the mention is **substantively relevant** to the principal point, story, or argument of the clip. Many times speakers will refer to a place briefly or refer to it in passing; this does not mean it is a substantively relevant mention. 

Apply the tag only if the mention of the place is substantively relevant to the clip. If the mention of place does not seem substantive, do not tag the clip with that location.

There are several possible ways for a place to be substantively relevant to a clip. For example:
- More than a sentence of text is devoted to describing the place or its significance; or
- The place is mentioned as a setting or context for the events that are being described in the longer context of the clip, and not just the sentence or two surrounding the place; or
- The place is used as a example of some larger phenomena, or to illustrate a point, and that example is discussed for a substantive amount of the clip – say, more than 2 sentences, or as an overarching idea that frames the entire meaning of the clip.

There are several indications that a mention of a place is NOT substantively relevant and should not be extracted. For example:
- The place is mentioned in passing without elaboration or indication that it is important to the events in the clip; or
- The place is mentioned as an origin or destination, without further elaboration; or
- The place is mentioned in a list with more than two other examples, and is not elaborated upon, e.g. only being discussed for 1 sentence.

## Labeling rules

For each place you extract, return it together with an aggregation label:

- Give the **place** exactly as it is mentioned or referenced in the clip, at whatever geographic level it appears — a neighborhood, city, federal state or administrative region, country, or (supra-national) region.
- Then give its aggregation label:
  - A neighborhood, city, or federal state / administrative region → the **country** it is in.
  - A country → its own **country** name.
  - A (supra-national) region → an **acceptable region** from the list given below (drawn from the United Nations Geoscheme), chosen by geographic proximity to the place mentioned.

When a place is only referenced indirectly - through a government, regime, political leader, landmark, natural feature, institution, etc. — extract the place it points to at the most sensible geographic level (e.g. "the Brazilian government" → Brazil; "the mayor of Belgrade" → Belgrade; a named university → the city it is in), and then aggregate that place to its country or acceptable region exactly as above.

Return two lists:

- `countries`: one entry per neighborhood / city / state / country place, each as `{place, country}`, where `place` is the mention as it appears and `country` is its common English name (free text).
- `regions`: one entry per supra-national place, each as `{place, region}`, where `region` is chosen from the acceptable-regions list exactly as written.

A place gets a country **or** a region, never both. If the clip is not substantively about any place, return empty lists.
