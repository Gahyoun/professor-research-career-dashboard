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

Unknown abbreviations are not expanded by guessing. For example, `CIT`, `IIT`,
`IIT@MIT`, `UST`, `KNUST`, `KUTE` and `UNED` need institution/context verification
before a global display alias can be added. `KAUST` also remains unchanged because
its public degree records currently carry KR country values, conflicting with the
Saudi institution's identity. Resolve those source records in the data workflow.
