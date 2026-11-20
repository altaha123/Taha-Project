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
   a line below with its credit (the author), source (the page it came from)
   and license. license_url links the licence where it has a page, and changes
   says what was done to the picture, which a Creative Commons licence asks to
   be told. investor-pictures.test.js fails on an id the backend does not
   have, a file that is missing or left over, a photograph with no credit, and
   a picture linked from a host that is not the logo host.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var PICTURES = {
    /* Authum is listed on NSE as AIIL. */
    'authum': { kind: 'logo', src: 'https://images.dhan.co/symbol/AIIL.png' },

    /* Wikimedia Commons, where the file's own page says who it is of. The
       960 px rendering, cropped to the head and shoulders. */
    'porinju-veliyath': {
      kind: 'photo', src: 'assets/investors/porinju-veliyath.jpg',
      credit: 'Viveq78', source: 'https://commons.wikimedia.org/wiki/File:Porinju_Veliyath.jpg',
      license: 'CC BY-SA 4.0', license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
      changes: 'cropped'
    },

    /* Also Commons: a still from The Nudge Institute's own recording of its
       Charcha 2020 closing session, which it published under CC BY. It is a
       video call, so it is soft; it is here because its licence can be
       followed back to the people who made it. */
    'ashish-dhawan': {
      kind: 'photo', src: 'assets/investors/ashish-dhawan.jpg',
      credit: 'The Nudge Institute', source: 'https://commons.wikimedia.org/wiki/File:AshishDhawan.png',
      license: 'CC BY 4.0', license_url: 'https://creativecommons.org/licenses/by/4.0/',
      changes: 'cropped'
    }

    /* NOT HERE, AND WHY
       Vijay Kedia has a file on Commons (File:VijayKedia.jpg, CC BY-SA 3.0,
       uploaded as the uploader's own work), and the photograph's embedded
       copyright line names a photography studio instead. Two different
       owners for one picture is a licence nobody can rely on, so it is left
       out until one of them says so.

       Commons was searched by name for everybody else in the table on
       20 November 2026 and holds no photograph of them. */
  };

  root.AltahaInvestorPictures = PICTURES;
  if (typeof module !== 'undefined' && module.exports) module.exports = PICTURES;
})(typeof window !== 'undefined' ? window : globalThis);
