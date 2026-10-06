---
id: 2026-09-29_suzuki-miyaura-coupling-002
date: '2026-09-29'
title: SPhos Pd G3 110°C 600s
experiment_type: Suzuki-Miyaura coupling
objective: 'Suzuki-Miyaura coupling in flow: 3-bromoquinoline with 3,5-dimethylisoxazole-4-boronic
  acid pinacol ester'
equipment:
- flow reactor
materials:
- SPhos Pd G3
- 3-bromoquinoline
- 3,5-dimethylisoxazole-4-boronic acid pinacol ester
- DBU
- THF
- water
parameters:
- name: temperature
  value: 110 °C
  controllable: true
- name: residence time
  value: 600 s
  controllable: true
- name: catalyst loading
  value: 1.2 mol%
  controllable: true
- name: catalyst
  value: SPhos Pd G3
  controllable: true
results: yield 33.8 %, TON 28.2
symptom:
  category: low_value
  description: 수율 또는 TON 목표 미달 (목표 수율 78.67 %, TON 65.56)
suspected_causes: []
actions_taken: []
notes: Test whether increasing temperature and residence time rescues SPhos Pd G3
  performance while holding catalyst and loading fixed; expect higher yield and TON
  than obs:a002.
references: []
resolution:
  resolved: false
  actual_cause: null
  note: ''
followup_of: 2026-09-29_suzuki-miyaura-coupling-001
needs_review: false
---

## 원문 로그

Test whether increasing temperature and residence time rescues SPhos Pd G3 performance while holding catalyst and loading fixed; expect higher yield and TON than obs:a002.

결과: yield 33.8 %, TON 28.2

출처: labgene pilot-02 baseline-r1-e001:a003

## 정리

SPhos Pd G3 110°C 600s 조건에서 yield 33.8 %, TON 28.2. 목표 미달.
