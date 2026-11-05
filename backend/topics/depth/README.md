# 인용 깊이 비교 — 전체 교수 커뮤니티가 depth 1·2·3에서 얼마나 바뀌는가

교수 개인 단위(`build_release_topics.py`의 `build_one`)가 아니라 **전체 교수 논문을 한 망에
놓고** 커뮤니티를 찾는다. 같은 비교를 depth 1, 2, 3에서 반복해 커뮤니티가 얼마나 바뀌는지
잰다. 참고문헌(refs)과 피인용(cites) 두 채널은 따로 돌리고 섞지 않는다.

## 현재 결정 (2026-11-05): depth 1, 위아래, 고정 seed Louvain

depth 2·3은 규모 대비 이득이 작다고 보고 쓰지 않는다. 쓰는 것은 **참고문헌(위) + 피인용(아래)
depth 1** 하나다. 전체 교수 논문을 한 망에 놓고 **Louvain을 seed 고정으로 한 번** 돌린다.

```bash
DB=professor_affiliation_timeline_through_2026.sqlite
S=backend/topics/depth
# 위: 대시보드 토픽 빌드가 이미 받아 둔 참고문헌을 재사용하고, 빠진 것만 API로 받는다
python3 -I $S/citation_layers.py import-cache --db $DB --channel refs --cache <build_release_topics --cache 경로>
python3 -I $S/citation_layers.py fetch --db $DB --channel refs --layer 1 --env-file ~/.openalex.env
# 아래: 출판 후 3년 안의 피인용. 창이 덜 닫힌 최근 논문도 지금까지의 피인용으로 포함한다
python3 -I $S/citation_layers.py fetch --db $DB --channel cites --layer 1 --include-open-windows --env-file ~/.openalex.env
# 분할
python3 -I $S/faculty_louvain.py --db $DB --out runs/louvain                    # 위+아래
python3 -I $S/faculty_louvain.py --db $DB --out runs/louvain_refs --channels refs   # 비교용
```

`faculty_louvain.py` 는 대시보드의 연구자별 규칙(`build_release_topics.py`)을 전체 교수에 한 번
적용한다. 규칙은 공유 이웃 c_ij ≥ 2, 가중치 Salton 코사인 c_ij/√(|N_i||N_j|), Louvain
resolution 1.05, seed 4다. 이웃 N은 참고문헌과 피인용의 합집합이다. 같은 논문이라도 "인용한
논문"과 "인용해 준 논문"은 다른 특징으로 둔다. Louvain은 igraph multilevel(C 구현)로 돌린다.
seed는 python-igraph가 쓰는 Python `random` 에 고정하고, 같은 seed로 두 번 돌려 결과가 같은지
`summary.json` 의 `rerun_identical` 에 기록한다. `--backend networkx` 는 대시보드와 같은
구현이지만 전수에서는 느리다.

- **인계서 §4와의 관계.** 저장은 두 채널을 그대로 분리한다(`cd_refs`, `cd_citers`). 합치는 것은
  분할 단계뿐이다. 공유 이웃 중 각 채널의 비중과 한 채널만으로 생긴 링크 수를 `summary.json` 에
  남긴다. 위·아래 분할과 `--channels refs` 분할을 같이 보면 피인용이 바꾼 부분이 드러난다.
- **고정 seed는 하나의 답일 뿐이다.** `--stability-seeds` 로 다른 seed와의 AMI를 함께 적는다.
- **최근 논문은 아래 이웃이 적다.** 노출 기간이 짧기 때문이다. 코사인이 크기를 정규화하지만,
  최근 논문의 소속 커뮤니티는 주로 참고문헌이 정한다.
- 합성 데이터 3만 편(참고문헌만)에서 8초, 0.2 GB였다. 실데이터는 고전 허브 때문에 링크가 훨씬
  많을 수 있다. 메모리가 모자라면 `--chunk` 를 줄인다.

아래 depth 비교 도구(`depth_sweep.py`)는 depth를 다시 검토할 때를 위해 남겨 둔다.

| 파일 | 역할 |
| --- | --- |
| `faculty_louvain.py` | 위+아래 depth 1, 전체 교수 고정 seed Louvain |
| `citation_layers.py` | OpenAlex 층별 수집기. 재개 가능. `refs` layer 1이 인계서의 T1이다 |
| `depth_sweep.py` | `run`: 한 채널에서 깊이 비교 / `compare`: 두 채널의 교차 비교 |
| `cdcommon.py` | id 정규화, 저장 스키마 |
| `backend/scripts/test_citation_depth.py` | 가짜 OpenAlex와 합성 인용 세계로 하는 종단 테스트 |

의존성: `numpy scipy scikit-learn`, 커뮤니티 탐색에 `python-igraph leidenalg`. 이 둘이
없으면 networkx Louvain으로 대신하는데, 15만 노드에서는 느리다.

---

## 1. 실행 순서

```bash
DB=professor_affiliation_timeline_through_2026.sqlite
S=backend/topics/depth

# 0) 범위 확인: 수집 대상 수, 예상 호출 수, identity_decision 분포
python3 -I $S/citation_layers.py plan  --db $DB --channel refs --layer 1

# 1) 참고문헌 layer 1 (= T1). 중단돼도 같은 명령을 다시 실행하면 이어서 받는다
python3 -I $S/citation_layers.py fetch --db $DB --channel refs --layer 1 --env-file ~/.openalex.env
python3 -I $S/citation_layers.py status --db $DB --channel refs   # T1 수용 기준(80%)을 연대별로 출력

# 2) layer 2의 정확한 범위와 비용은 layer 1이 끝나야 알 수 있다
python3 -I $S/citation_layers.py plan  --db $DB --channel refs --layer 2
python3 -I $S/citation_layers.py fetch --db $DB --channel refs --layer 2 --env-file ~/.openalex.env

# 3) 피인용 layer 1 (출판 후 3년 창, 2025년까지 완결된 해만)
python3 -I $S/citation_layers.py fetch --db $DB --channel cites --layer 1 --env-file ~/.openalex.env

# 4) 깊이 비교. 먼저 표본으로 돌려 보고, 그다음 전수로
python3 -I $S/depth_sweep.py run --db $DB --channel refs  --depths 1,2,3 --out runs/refs --sample-works 20000
python3 -I $S/depth_sweep.py run --db $DB --channel refs  --depths 1,2,3 --out runs/refs
python3 -I $S/depth_sweep.py run --db $DB --channel cites --depths 1,2   --out runs/cites
python3 -I $S/depth_sweep.py compare runs/refs runs/cites --out runs/cross
```

- 주 DB를 건드리지 않으려면 두 스크립트 모두에 `--store collected.sqlite` 를 준다.
- 수집 결과에는 인계서 T1과 같은 모양의 뷰 `work_references(work_id, referenced_work_id)` 가
  생긴다. id 접두어는 주 DB의 것을 따르므로 `space_fit.py --refs-sql` 을 그대로 쓸 수 있다.
- API 키는 `$OPENALEX_API_KEY` 나 `--env-file` 에서 읽고 출력하지 않는다. 키가 없으면 수집을
  거부한다. `--no-key` 는 테스트용이다.

**수집되지 않은 깊이는 분석하지 않는다.** 그 깊이에서 이웃이 필요한 노드 중 수집된 비율이
`--min-coverage`(기본 98%)에 못 미치면 그 깊이는 건너뛰고, 이유를 `summary.json` 에 적는다.
덜 받은 층은 이웃이 적게 보이므로, 그 상태로 비교하면 차이가 깊이 효과인지 수집 공백인지
가릴 수 없다.

---

## 2. 설계 — 무엇을 고정하고 무엇만 바꾸는가

| 고정 | 이유 |
| --- | --- |
| **노드 집합** = 교수 논문 중 가장 얕은 깊이 벡터가 비지 않은 것(core) | 노드가 깊이마다 다르면 분할 간 AMI를 정의할 수 없다 |
| **커뮤니티 수 K** (해상도 이분 탐색으로 깊이마다 맞춤) | 깊이가 깊어지면 망이 빽빽해져 같은 해상도에서도 K가 저절로 줄어든다. K를 맞추지 않으면 "커뮤니티가 변했다"가 밀도 효과가 된다. 기본 K = 30, 60, 120 |
| 임베딩 차원·kNN k·알고리즘 | 깊이 외의 차이를 없앤다 |

바뀌는 것은 "두 논문이 무엇을 공유하면 가까운가" 하나다.

- **hop 층** `N_h` = 그 논문에서 최소 거리 h인 노드(`--mode reach`, 기본). `paths` 는 경로 수를 쓴다.
- **depth d 벡터** = `N_1 … N_d` 를 TF-IDF로 가중하고, 각 층을 행 단위로 L2 정규화한 뒤
  `α^(h−1)` 를 곱해 합친다(`--layer-weight balanced`, α=1). depth 2의 층은 depth 1보다
  수십 배 크다. 층별로 정규화하지 않으면 깊은 층이 방향을 독점해 "깊이를 더했다"가 아니라
  "깊은 층으로 갈아탔다"가 된다.
- **IDF** = `ln((1+N)/(1+df))`, df는 eligible 교수 논문 전체에서 센다. sklearn 식의 `+1` 을
  쓰지 않는다. 모든 논문이 닿는 고전은 정보가 없으므로 가중치가 0이어야 한다. 합성 데이터
  테스트에서 `+1` 을 두면 고전 5편만 있는 depth 3 층이 depth 1과 같은 무게를 받아 커뮤니티를
  뭉갰다(depth 1↔3 AMI 0.28). 빼면 depth 3이 depth 2와 같아졌다(AMI 1.00).
- `min_df=2` 는 한 논문만 닿는 특징을 뺀다. 그런 특징은 유사도에 기여하지 않는다.
  `--max-df` 는 기본 1.0(자르지 않음)이다.
- 임베딩: 행 쪽 무작위 SVD 128차원(`space_fit` 과 같은 차원) → 단위벡터 → 코사인 kNN 그래프
  (k=20) → Leiden(RB configuration, seed 5개, 반복 2회 = leidenalg 기본). 행(교수 논문)이 열
  (조상 논문)보다 훨씬 적으므로 QR을 행 쪽에서만 한다. 같은 결과에 sklearn `TruncatedSVD` 보다
  약 5배 빠르다(10k × 106만 열, 910만 항목에서 14초 대 79초). `--embed none` 은 SVD 없이 희소
  코사인으로 kNN을 잡는다. SVD 절단에 결과가 기대지 않는지 보는 강건성 점검용이다.
- Leiden `--leiden-iterations -1`(수렴까지)은 해상도가 그래프를 잘게 쪼개는 구간에서 매우
  느리다. 3만 노드에서 111초였고, 기본값 2회는 4.8초였다.

**피인용 채널** — 창은 *초점 논문의 출판연도 + W년* 으로 고정하고 **모든 홉에 적용**한다.
피인용자의 피인용자도 같은 기한 안에 있어야 한다. 노출 기간이 논문마다 같아야 연도 간 비교가
기울지 않는다. 창이 아직 닫히지 않은 논문(year + W > `--last-complete-year`)은 빠진다.

---

## 3. 측정 — 모든 비교에 잡음 바닥이 짝으로 붙는다

깊이마다 무작위 선택이 전부 다른 **복제 두 벌**을 만든다. A는 SVD seed s와 Leiden seed 0…,
B는 SVD seed s+1과 Leiden seed 1000…을 쓴다. 잡음 바닥은 *같은 깊이의 A 대 B*이고, 깊이 간
비교는 *한 깊이의 A 대 다른 깊이의 B*(및 그 반대)다. 둘 다 모든 무작위 선택이 다르므로 바로
비교할 수 있다. 깊이 간 비교에 같은 SVD seed를 쓰면 공유된 무작위 사영이 일치를 부풀린다.
합성 데이터에서 그렇게 하면 깊이 간 kNN 겹침이 0.41, 바닥이 0.12로 나와 "깊이를 바꾼 쪽이 더
안정적"이라는 역설이 생겼다.

| 지표 | 무엇 | 잡음 바닥 |
| --- | --- | --- |
| kNN 이웃 보존 | 각 논문의 k-이웃 집합 Jaccard 평균. 분할도 해상도도 거치지 않는다 | 같은 깊이 A 대 B |
| AMI, ARI | 깊이 간 분할 일치 (A×B 쌍 전부의 평균 ± sd) | 같은 깊이 A 대 B (seed² 쌍) |
| 생존율 | 한 깊이의 커뮤니티 중 다른 깊이에 Jaccard ≥ 0.5 짝이 있는 비율(노드 가중, 양방향) | 같은 깊이 A 대 B |
| 최대 커뮤니티 비율, 조각 비율 | 깊은 층이 한 덩어리로 녹는지 | — |
| AMI vs OpenAlex subfield | **기술용.** OpenAlex 분류에도 인용 신호가 들어가므로 검증으로 쓰지 않는다 | — |
| 교수 Q̂ 순위상관 | 교수별(통합)·교수-연도별 Rao Q̂ = (2n/(n−1))(1−R²)의 Spearman. **깊이가 하류 결론을 바꾸는가** | — |
| 교차 채널 AMI (`compare`) | refs 분할 대 cites 분할. 구성에 쓰지 않은 신호로 하는 검증(인계서 §4) | 각 채널의 seed 바닥 |

출력: `summary.json`(전체 수치와 파라미터), `report.md`(표), `partitions.npz`(core work id와
K·깊이·seed별 라벨), `professor_qhat.csv`.

---

## 4. 판독 규칙 — 데이터를 보기 전에 고정한다

임계값은 판단이다. 바꾸려면 **결과를 보기 전에** 이 절을 고치고 커밋한다(인계서 §5 당사자성).
`floor(d)` = depth d의 A 대 B AMI(§3), `m = min(floor(1), floor(d))`.

1. **중복** — 세 K 모두에서 AMI(1,d) ≥ m − 0.02 이고 교수 Q̂ Spearman(1,d) ≥ 0.95 이면
   depth d는 정보를 더하지 않는다. depth 1을 쓴다. 더 싸고 고전 허브에 덜 민감하다.
2. **변화** — 세 K 중 둘 이상에서 AMI(1,d) < m − 0.05 이면 깊이가 구조를 바꾼다. 어느 쪽이
   나은지는 subfield 일치로 고르지 않는다. 독립 채널인 cites depth 1과의 교차 AMI로 고른다.
   교차 채널이 없으면 깊이를 민감도 축으로 두고, 양쪽에서 재현되는 결론만 싣는다.
3. **용해** — 최대 커뮤니티가 노드의 50%를 넘으면 depth d는 퇴화다. 비교에서 뺀다. 목표 K에
   도달하지 못한 경우(허용 오차 3% 밖, `report.md` 에 ✗)는 그 K에서만 비교하지 않는다. 구조에
   그 입도의 단계가 없다는 뜻일 수 있으므로 다른 K의 결과로 판단한다.
4. **하류 판정** — 통합 Q̂ Spearman(1,d) ≥ 0.9 이면 이후 분석(Q0, H2 등)은 깊이에 대해
   강건하다고 보고 depth 1 결과를 주 결과로 쓴다. 0.9 미만이면 depth d 결과를 병기한다.

1과 2 사이(0.02–0.05)는 "판단 불가"로 보고하고, seed 수를 늘려(`--seeds 10`) 다시 잰다.

---

## 5. 비용과 규모

| 층 | 호출 | 비고 |
| --- | --- | --- |
| refs layer 1 | 교수 논문 수 / 100 (≈1,500) | 정확. `plan` 이 출력 |
| refs layer 2 | layer 1에서 나온 고유 참조 논문 수 / 100 | layer 1 직후 `plan` 이 정확히 출력. 수백만 편이면 수만 회 |
| refs layer 3 | 수천만 노드 | API로는 비현실적. 아래 스냅샷 경로 |
| cites layer 1 | 묶음(50편) 수 + 페이지 수 | `plan` 은 cited_by_count 합으로 상한을 낸다 |

호출당 비용 기본값 $0.001 은 `references/openalex-api.md` 의 메모를 따른다. 실제 단가는
`plan --cost-per-call` 로 바꾼다.

**분석 규모(합성 데이터 실측, 4코어 · 15 GB 컨테이너)** — 교수 논문 3만 편, depth 2 특징
열 124만·항목 2,770만, K = 30·60·120, seed 5 × 복제 2에서 전 과정 약 10분, 최대 메모리 3.2 GB.
대부분은 SVD(복제 두 벌, 약 2분)와 Leiden 해상도 이분 탐색(K·깊이당 약 1.5분)이다. 15만 편
전수는 이보다 몇 배 걸릴 것으로 보이지만 실측하지는 않았다. 먼저 `--sample-works 20000` 으로
돌린다. 메모리 상한은
`--max-gb`(기본 6)이다. 넘을 깊이는 계산 전에 건너뛰고 이유를 남긴다. 줄이는 순서:
`--sample-works` → `--max-df 0.05`(이 경우 결과에 명시) → 더 큰 기계.

**depth 3 스냅샷 경로(미검증)** — OpenAlex 전체 스냅샷의 works 파일에서, 필요한 노드
(`citation_layers.py status` 가 layer 3 대기로 세는 노드)의 `referenced_works` 를 `cd_refs(src,
dst)` 정수 쌍으로 넣고, 각 노드에 `cd_log(work, 'refs', 3, 'ok', n, NULL, at)` 를 쓰면
`depth_sweep.py` 는 그대로 동작한다. 저장 형식이 정수 쌍이라 DuckDB 등으로 바로 적재할 수 있다.

---

## 6. 알아둘 것

- **기본 works SQL은 `identity_decision IS NULL` 행을 조용히 버린다.** `x != 'namesake_paper'`
  는 NULL에서 NULL이기 때문이다. `plan` 이 NULL 건수를 경고한다. 포함 여부는 `--works-sql` /
  `--links-sql` 로 명시한다. KOAD `review` 를 keep/drop/flag 세 정책으로 돌릴 때도 같은 인자를
  쓴다(인계서 §4).
- OpenAlex가 돌려주지 않은 id(병합·철회)는 `missing` 으로 기록하고 다시 요청하지 않는다.
  10편 이상 요청했는데 0편이 오면 "조용한 빈 응답"으로 보고 기록하지 않는다. 다음 실행에서
  다시 받는다. `X-RateLimit-Remaining` 이 0이면 멈춘다.
- 커뮤니티 라벨은 **가시성 지표**다. 주 측정은 연속 좌표다(인계서 §4: 이산 전이와 연속 이동을
  섞지 않는다). 이 도구의 산출은 `space_fit.py` 입력을 depth 1로 할지 1+2로 할지 정하는 근거다.
- 합성 데이터 테스트는 코드가 설계대로 계산하는지를 확인할 뿐이다. 실제 깊이 효과의 크기는
  실데이터에서만 나온다.
