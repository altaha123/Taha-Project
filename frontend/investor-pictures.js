/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — investor-pictures.js

   The picture beside an investor's name, keyed by the id in
   backend/investors.py. An investor with no entry here gets their initials,
   which is the right answer more often than it sounds.

   A PICTURE IS A CLAIM, LIKE AN ALIAS IS
   The investor table holds a rule: every association was decided by a person
   and is written down. A face is the same kind of statement about a named
   private individual, and it is held to the same rule. So nothing here is
   found by searching a name and taking the first result. A common name
   returns several people, the pictures passed around of the more private
   investors are often of somebody else, and a wrong face on a real person's
   holdings is worse than no face.

   WHAT MAY GO IN
     photo   A photograph whose source page says who it is of, and which this
             site is allowed to show: a free licence (Wikimedia Commons), or
             the person's or the photographer's own permission. It is kept
             here as a file, not linked from somebody else's server, and it
             carries its author, its licence and its source, which the page
             prints. A picture off a search engine or a social network is
             somebody's copyright and is not in this list.
     logo    A company's own mark, shown beside the company's own name. A
             listed company's comes from the image host the wealth desk
             already uses, keyed by NSE symbol.

   TO ADD ONE
   Save the picture square, about 256 px, in assets/investors/<id>.jpg, and add
   a line below. investor-pictures.test.js fails on an id the backend does not
   have, a file that is missing or left over, a photograph with no credit, and
   a picture linked from a host that is not the logo host.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var PICTURES = {
    /* Authum is listed on NSE as AIIL. */
    'authum': { kind: 'logo', src: 'https://images.dhan.co/symbol/AIIL.png' }
  };

  root.AltahaInvestorPictures = PICTURES;
  if (typeof module !== 'undefined' && module.exports) module.exports = PICTURES;
})(typeof window !== 'undefined' ? window : globalThis);
