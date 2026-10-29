Showcase pairs for the Photo Enhancer page (hero slider + "See the transformations" gallery).

Add two files per example, with the same name:

    01-bedroom-before.jpg   <- a real, unedited photo
    01-bedroom-after.jpg    <- the same photo run through Photo Enhancer

Rules:
  * The part after the number is the label shown on the card ("Bedroom").
  * The leading number only sets the order; the first pair is used in the hero slider.
  * Use the SAME aspect ratio for before and after (3:2 landscape works best).
  * The hero slider appears with 1 or more pairs; the gallery with 2 or more (up to 6 are shown).

The three pairs currently here are DEMOS: each "before" is a stock room photo from the site's own
assets, deliberately degraded (underexposed, colour cast, tilted, soft, noisy), and each "after" is
that degraded photo run through the real Photo Enhancer pipeline. Replace them with real pairs from
your own listings whenever you have them - just overwrite or delete the files.

With no pairs here, the hero shows a "what your photos get" card instead and the gallery is hidden.
Run `collectstatic` on the server after changing files.
