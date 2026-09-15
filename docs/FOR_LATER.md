# For later

Deferred ideas; recording an item here does not change solver behaviour.

## Earliest allowed epoch for known photographic processes

Recorded 2026-09-15. Deferred proposal for `go4.sh`; not implemented.

Consider an explicit, user-supplied earliest-epoch setting for both stellar and
planetary epoch searches. Record the chosen bound and its justification in the
results as a declared input-collection assumption, separate from an inferred
exposure date. Keep the existing current-time upper bound. Leave legacy `go.sh`
unchanged.

Colour alone does not justify a post-1940 cutoff: experimental three-colour
photography dates to 1861, commercial Autochrome plates to 1907, and Kodachrome
multilayer colour film to 1935. A 1935 or later lower bound needs knowledge of the
input collection or photographic process. Do not infer it merely from RGB
channels: scans, colourised monochrome photographs and coloured annotations can
also produce RGB files. Do not derive the bound from hidden exposure metadata.

Historical references:
- [National Science and Media Museum: Autochrome history](https://blog.scienceandmediamuseum.org.uk/autochromes-the-dawn-of-colour-photography/)
- [Kodak: Exploring the Color Image](https://www.kodak.com/content/products-brochures/Film/Exploring-the-Color-Image.pdf)
