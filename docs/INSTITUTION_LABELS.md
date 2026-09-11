# Institution display names

Institution labels use full English names throughout the career view, hypergraph,
institution statistics and Sankey (including CSV). `institutionDisplayName` in
`frontend/src/schoolIdentity.ts` is the common presentation function.
`institutionSearchText` also exposes the corresponding Korean and abbreviated
names to researcher searches.

Display aliases match whole strings. They do not modify public release files,
metadata joins, institution IDs, filters, grouping, or dated succession rules.
Historical predecessor names and explicit campus/hospital suffixes remain distinct.
Long Sankey names wrap, with label space reserved separately from proportional
node and ribbon thicknesses.

Domestic shorthand already paired with an English university name in the public
release is included explicitly (for example, `Korea_sejong` retains Sejong Campus).
Display normalization accepts typographic dash variants, without changing the
matching normalization. Degree detail labels still use the original display field;
supplemental matching labels must not replace a more complete school name.

Official sources checked on 2026-09-09:

- [KAIST](https://www.kaist.ac.kr/en/): Korea Advanced Institute of Science and Technology
- [UNIST](https://www.unist.ac.kr/unist/introduction/academic.do): Ulsan National Institute of Science and Technology
- [DGIST](https://scholar.dgist.ac.kr/about/policy): Daegu Gyeongbuk Institute of Science and Technology
- [GIST](https://ipa.gist.ac.kr/kr/html/sub01/0102.html): Gwangju Institute of Science and Technology
- [Chung-Ang University](https://neweng.cau.ac.kr/cms/FR_CON/index.do?MENU_ID=20)
- [Gyeongsang National University](https://www.gnu.ac.kr/eng/main.do)
- [Kangwon National University](https://global.kangwon.ac.kr/english/contents.do?key=2000): the merged institution uses this English name too.
- [The Hong Kong University of Science and Technology](https://hkust.edu.hk/about)
- [Korea National Open University](https://www.knou.ac.kr/knou/index.do)
- [Korea National University of Education](https://www.knue.ac.kr/eng/index.do)
- [Korea National University of Transportation](https://www.ut.ac.kr/english/sub01_01.do)
- [Dongguk University WISE Campus](https://web.dongguk.ac.kr/eng/page/173)
- [Korea University Sejong Campus](https://sejong.korea.ac.kr/eng/index.do)
- [Konkuk University GLOCAL Campus](https://www.kku.ac.kr/cms/FR_CON/index.do?MENU_ID=510)
- [Hanyang University ERICA Campus](https://www.hanyang.ac.kr/web/eng/erica-campus1/)
- [Yonsei University Mirae Campus](https://www.yonsei.ac.kr/en_sc/1819/subview.do)
- [University of Ulsan](https://biology.ulsan.ac.kr/)
- [Andong National University](https://www.andong.ac.kr/eng/html.do): preserve the historical institution's name.
- [Jungwon University](https://www.jwu.ac.kr/index.jsp)
- [Kosin University](https://www.kosin.ac.kr/eng/)
- [Daegu Catholic University](https://www.cu.ac.kr/index.php)
- [Sangmyung University](https://www.smu.ac.kr/eng1/index.do)
- [Hongik University](https://www.hongik.ac.kr/en/about/about-hongik.do)
- [Kyungnam University](https://www.kyungnam.ac.kr/sites/en/index.do)
- [Seowon University](https://www.seowon.ac.kr/)

`Donggkuk_wise` is a display-only typo alias: one of its public faculty records
also identifies the same researcher's current institution explicitly as Dongguk
University (WISE Campus). No institutional membership keys are rewritten.

Unknown abbreviations are not expanded by guessing. For example, `CIT`, `IIT`,
`IIT@MIT`, `UST`, `KNUST`, `KUTE` and `UNED` need institution/context verification
before a global display alias can be added. `KAUST` also remains unchanged because
its public degree records currently carry KR country values, conflicting with the
Saudi institution's identity. Resolve those source records in the data workflow.
Unresolved spellings such as `Konju`, `Myongi`, `Deagu` and `Sila` also retain the
source text until the underlying institution is confirmed.

## Reviewed identity aliases (2026-09-11)

These reviewed aliases are in the shared `canonicalSchool` registry, so they also
unify filter options, Sankey totals and routes, hypergraph institution keys, and
institution-bound metadata joins. They retain the original release fields and do
not infer departments or merge distinct campuses. Search accepts the old spellings.

| Canonical institution | Observed release variants | Basis |
| --- | --- | --- |
| University of Illinois Urbana-Champaign | University of Illinois at Urbana - Champaign; Illinois at Urbana - Champaign; Illinois-Urbana/Champaign | The [Illinois System writing guide](https://www.uillinois.edu/erc/brand_and_marketing/brand/style/writing_style_guide) records the removal of `at` from the name. All variants explicitly identify Urbana-Champaign. |
| University of Illinois Chicago | Illinois at Chicago | The same official guide identifies Chicago separately and records its name without `at`. |
| University of Wisconsin–Madison | University of Wisconsin-Madison; Wisconsin-Madison | The [official editorial guide](https://editorial-styleguide.strategiccommunication.wisc.edu/term/university-of-wisconsin-madison-the/) specifies an en dash for Madison. |
| Colorado School of Mines | Colorado School of Mines. | A trailing period on the [official school name](https://www.mines.edu/about/). |
| Sri Venkateswara University | Sri Venkateswara Physics | The source degree's author and year match a [research-lab biography](https://sites.google.com/site/nanogachon/members) that explicitly names the university and a physics PhD. The university also lists its [Physics department](https://svuniversity.edu.in/departments_cs/physics/). This corrects a department token in the school field; it neither verifies all department fields nor deduplicates researcher records. |

`Illinois` alone is unresolved. Illinois Chicago, Illinois Institute of Technology,
Wisconsin–Eau Claire and Medical College of Wisconsin remain separate from the
Urbana-Champaign and Madison groups.
