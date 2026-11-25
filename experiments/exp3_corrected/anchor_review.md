# Surface anchor review

Proposed by `openai/gpt-5.6-luna`, reviewed by `openai/gpt-5.6-terra`.

**844 kept, 51 dropped.** Every drop is listed with the
reviewing model's stated reason, so the set can be checked without rerunning it.

Until a clinician has read this sheet end to end, the resource header reads
`vetted_by: llm` and every result leaning on a `pheno=` target should say so.
Reading it and passing `--signed-by` is what makes the stronger claim true.

| phenotype | surface | verdict | reason |
|---|---|---|---|
| alcohol_use_disorder | `alcohol use disorder` | keep | Exact diagnosis term |
| alcohol_use_disorder | `alcohol use d/o` | keep | Common abbreviated diagnosis term |
| alcohol_use_disorder | `alcohol use disorder (aud)` | keep | Diagnosis with standard abbreviation |
| alcohol_use_disorder | `aud` | keep | Standard abbreviation for diagnosis |
| alcohol_use_disorder | `alcohol dependence` | keep | Legacy term for alcohol use disorder |
| alcohol_use_disorder | `alcohol dependence syndrome` | keep | Clinical synonym for alcohol dependence |
| alcohol_use_disorder | `alcohol dep` | keep | Common shorthand for dependence |
| alcohol_use_disorder | `alcoholism` | keep | Common clinical synonym |
| alcohol_use_disorder | `chronic alcoholism` | keep | Chronic form of alcoholism |
| alcohol_use_disorder | `alcohol addiction` | keep | Clinical synonym for alcohol use disorder |
| alcohol_use_disorder | `alcohol abuse` | keep | Legacy alcohol-related diagnostic term |
| alcohol_use_disorder | `alcohol abuse disorder` | keep | Variant phrasing for alcohol disorder |
| alcohol_use_disorder | `alcohol misuse` | keep | Clinical term for disordered alcohol use |
| alcohol_use_disorder | `problem drinking` | keep | Informal clinical alcohol disorder term |
| alcohol_use_disorder | `etoh use disorder` | keep | Common ethanol shorthand diagnosis |
| alcohol_use_disorder | `etoh use d/o` | keep | Abbreviated ethanol disorder term |
| alcohol_use_disorder | `etoh dependence` | keep | Ethanol shorthand for dependence |
| alcohol_use_disorder | `etoh dependence syndrome` | keep | Ethanol synonym for dependence syndrome |
| alcohol_use_disorder | `etoh dep` | keep | Common ethanol dependence shorthand |
| alcohol_use_disorder | `etoh abuse` | keep | Ethanol shorthand for alcohol abuse |
| alcohol_use_disorder | `etoh abuse disorder` | keep | Variant ethanol disorder phrasing |
| alcohol_use_disorder | `etohism` | keep | Clinical shorthand for alcoholism |
| alcohol_use_disorder | `alcohol use disorder, mild` | keep | Mild severity specified diagnosis |
| alcohol_use_disorder | `alcohol use disorder, moderate` | keep | Moderate severity specified diagnosis |
| alcohol_use_disorder | `alcohol use disorder, severe` | keep | Severe severity specified diagnosis |
| alcohol_use_disorder | `alcohol dependence, in remission` | keep | Dependence diagnosis with remission |
| alcohol_use_disorder | `alcohol use disorder, in remission` | keep | AUD diagnosis with remission |
| atrial_fibrillation | `atrial fibrillation` | keep | standard diagnosis name |
| atrial_fibrillation | `atrial fib` | keep | common informal diagnosis shorthand |
| atrial_fibrillation | `auricular fibrillation` | keep | established synonym for atrial fibrillation |
| atrial_fibrillation | `af` | keep | common clinical abbreviation |
| atrial_fibrillation | `a-fib` | keep | common punctuation variant |
| atrial_fibrillation | `a fib` | keep | common spaced abbreviation |
| atrial_fibrillation | `afib` | keep | common clinical abbreviation |
| atrial_fibrillation | `paroxysmal atrial fibrillation` | keep | recognized atrial fibrillation subtype |
| atrial_fibrillation | `paroxysmal af` | keep | common subtype abbreviation |
| atrial_fibrillation | `persistent atrial fibrillation` | keep | recognized atrial fibrillation subtype |
| atrial_fibrillation | `persistent af` | keep | common subtype abbreviation |
| atrial_fibrillation | `permanent atrial fibrillation` | keep | recognized atrial fibrillation subtype |
| atrial_fibrillation | `permanent af` | keep | common subtype abbreviation |
| atrial_fibrillation | `chronic atrial fibrillation` | keep | recognized atrial fibrillation descriptor |
| atrial_fibrillation | `chronic af` | keep | common descriptor abbreviation |
| atrial_fibrillation | `longstanding persistent atrial fibrillation` | keep | recognized atrial fibrillation subtype |
| atrial_fibrillation | `longstanding persistent af` | keep | common subtype abbreviation |
| atrial_fibrillation | `lone atrial fibrillation` | keep | recognized atrial fibrillation descriptor |
| atrial_fibrillation | `lone af` | keep | common descriptor abbreviation |
| atrial_fibrillation | `valvular atrial fibrillation` | keep | recognized atrial fibrillation classification |
| atrial_fibrillation | `valvular af` | keep | common classification abbreviation |
| atrial_fibrillation | `nonvalvular atrial fibrillation` | keep | recognized atrial fibrillation classification |
| atrial_fibrillation | `nonvalvular af` | keep | common classification abbreviation |
| atrial_fibrillation | `atrial fibrillation with rapid ventricular response` | keep | atrial fibrillation with rate qualifier |
| atrial_fibrillation | `af with rapid ventricular response` | keep | common abbreviated diagnosis phrasing |
| atrial_fibrillation | `af with rvr` | keep | common abbreviated diagnosis phrasing |
| chest_pain | `chest pain` | keep | Direct diagnosis term |
| chest_pain | `chest pains` | keep | Plural clinical diagnosis wording |
| chest_pain | `chest discomfort` | keep | Common chest pain equivalent |
| chest_pain | `chest pressure` | keep | Common chest pain equivalent |
| chest_pain | `chest tightness` | keep | Common chest pain equivalent |
| chest_pain | `chest heaviness` | keep | Common chest pain equivalent |
| chest_pain | `chest ache` | keep | Informal chest pain wording |
| chest_pain | `pain in chest` | keep | Direct anatomical phrasing |
| chest_pain | `pain of chest` | keep | Direct anatomical phrasing |
| chest_pain | `painful chest` | keep | Clinical symptom phrasing |
| chest_pain | `thoracic pain` | keep | Thoracic pain synonym |
| chest_pain | `thorax pain` | keep | Thoracic pain synonym |
| chest_pain | `pain in thorax` | keep | Thoracic anatomical phrasing |
| chest_pain | `precordial pain` | keep | Precordial chest pain term |
| chest_pain | `precordialgia` | keep | Established precordial pain diagnosis |
| chest_pain | `thoracalgia` | keep | Established chest pain synonym |
| chest_pain | `thoracodynia` | keep | Established chest pain synonym |
| chest_pain | `retrosternal pain` | keep | Retrosternal chest pain term |
| chest_pain | `substernal pain` | keep | Substernal chest pain term |
| chest_pain | `chest wall pain` | keep | Chest pain subtype |
| chest_pain | `chest-wall pain` | keep | Chest pain subtype |
| chest_pain | `anterior chest pain` | keep | Anatomic chest pain subtype |
| chest_pain | `anterior chest-wall pain` | keep | Anatomic chest wall pain |
| chest_pain | `central chest pain` | keep | Central chest pain subtype |
| chest_pain | `atypical chest pain` | keep | Clinical chest pain qualifier |
| chest_pain | `noncardiac chest pain` | keep | Clinical chest pain qualifier |
| chest_pain | `non-cardiac chest pain` | keep | Clinical chest pain qualifier |
| chest_pain | `musculoskeletal chest pain` | keep | Clinical chest pain subtype |
| chest_pain | `pleuritic chest pain` | keep | Clinical chest pain subtype |
| chest_pain | `exertional chest pain` | keep | Clinical chest pain qualifier |
| chest_pain | `chest pain at rest` | keep | Clinical chest pain qualifier |
| chest_pain | `chest pain syndrome` | keep | Chest pain diagnostic wording |
| chest_pain | `chest pain, unspecified` | keep | Unspecified chest pain diagnosis |
| chest_pain | `other chest pain` | keep | Other chest pain diagnosis |
| chest_pain | `cp` | keep | Common chest pain abbreviation |
| chest_pain | `c/p` | keep | Common chest pain abbreviation |
| chest_pain | `c.p.` | keep | Common chest pain abbreviation |
| chest_pain | `chest px` | keep | Informal chest pain abbreviation |
| chronic_kidney_disease | `chronic kidney disease` | keep | Exact diagnosis term |
| chronic_kidney_disease | `ckd` | keep | Standard chronic kidney disease abbreviation |
| chronic_kidney_disease | `chronic renal disease` | keep | Synonym for chronic kidney disease |
| chronic_kidney_disease | `chronic renal insufficiency` | keep | Older term for chronic kidney disease |
| chronic_kidney_disease | `chronic kidney insufficiency` | keep | Synonym for chronic kidney disease |
| chronic_kidney_disease | `chronic renal failure` | keep | Chronic kidney disease terminology |
| chronic_kidney_disease | `crf` | drop | Also means chronic respiratory failure |
| chronic_kidney_disease | `chronic kidney failure` | keep | Chronic kidney disease terminology |
| chronic_kidney_disease | `ckf` | keep | Abbreviation for chronic kidney failure |
| chronic_kidney_disease | `chronic kidney disease stage 1` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 1` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 2` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 2` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 3` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 3` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 3a` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 3a` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 3b` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 3b` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 4` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 4` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `chronic kidney disease stage 5` | keep | Specific CKD stage |
| chronic_kidney_disease | `ckd stage 5` | keep | Specific CKD stage abbreviation |
| chronic_kidney_disease | `end-stage renal disease` | keep | Advanced stage chronic kidney disease |
| chronic_kidney_disease | `end stage renal disease` | keep | Advanced stage chronic kidney disease |
| chronic_kidney_disease | `esrd` | keep | Standard end-stage renal disease abbreviation |
| chronic_kidney_disease | `end-stage kidney disease` | keep | Advanced stage chronic kidney disease |
| chronic_kidney_disease | `end stage kidney disease` | keep | Advanced stage chronic kidney disease |
| chronic_kidney_disease | `eskd` | keep | Standard end-stage kidney disease abbreviation |
| chronic_kidney_disease | `renal failure` | drop | May refer to acute renal failure |
| chronic_kidney_disease | `kidney failure` | drop | May refer to acute kidney failure |
| chronic_kidney_disease | `diabetic kidney disease` | keep | Diabetes-related chronic kidney disease |
| chronic_kidney_disease | `diabetic nephropathy` | keep | Diabetes-related chronic kidney disease term |
| chronic_kidney_disease | `hypertensive chronic kidney disease` | keep | Hypertensive chronic kidney disease subtype |
| chronic_kidney_disease | `hypertensive kidney disease` | keep | Hypertensive chronic kidney disease term |
| clostridioides_difficile | `clostridioides difficile infection` | keep | Full diagnosis name |
| clostridioides_difficile | `clostridium difficile infection` | keep | Former organism nomenclature |
| clostridioides_difficile | `c. difficile infection` | keep | Common abbreviated diagnosis |
| clostridioides_difficile | `c difficile infection` | keep | Common abbreviated diagnosis |
| clostridioides_difficile | `c. diff infection` | keep | Common clinical shorthand |
| clostridioides_difficile | `c diff infection` | keep | Common clinical shorthand |
| clostridioides_difficile | `cdiff infection` | keep | Common unpunctuated shorthand |
| clostridioides_difficile | `cdi` | keep | Standard infection abbreviation |
| clostridioides_difficile | `clostridioides difficile` | keep | Organism names diagnosis clinically |
| clostridioides_difficile | `clostridium difficile` | keep | Organism names diagnosis clinically |
| clostridioides_difficile | `c. difficile` | keep | Common organism shorthand |
| clostridioides_difficile | `c difficile` | keep | Common organism shorthand |
| clostridioides_difficile | `c. diff` | keep | Common organism shorthand |
| clostridioides_difficile | `c diff` | keep | Common organism shorthand |
| clostridioides_difficile | `cdiff` | keep | Common organism shorthand |
| clostridioides_difficile | `clostridioides difficile colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `clostridium difficile colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `c. difficile colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `c difficile colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `c. diff colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `c diff colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `cdiff colitis` | keep | Specific CDI colitis diagnosis |
| clostridioides_difficile | `clostridioides difficile enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `clostridium difficile enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `c. difficile enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `c difficile enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `c. diff enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `c diff enterocolitis` | keep | Specific CDI enterocolitis diagnosis |
| clostridioides_difficile | `pseudomembranous colitis` | drop | Can have non-CDI causes |
| clostridioides_difficile | `pseudomembranous enterocolitis` | drop | Can have non-CDI causes |
| clostridioides_difficile | `clostridioides difficile-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `clostridium difficile-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `c. difficile-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `c difficile-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `c. diff-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `c diff-associated disease` | keep | Established CDI disease term |
| clostridioides_difficile | `cdad` | keep | Standard CDI-associated disease abbreviation |
| clostridioides_difficile | `clostridioides difficile-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `clostridium difficile-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `c. difficile-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `c difficile-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `c. diff-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `c diff-associated diarrhea` | keep | Established CDI diarrhea term |
| clostridioides_difficile | `clostridioides difficile diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `clostridium difficile diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `c. difficile diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `c difficile diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `c. diff diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `c diff diarrhea` | keep | CDI described with diarrhea |
| clostridioides_difficile | `enterocolitis due to clostridioides difficile` | keep | Explicit causative organism diagnosis |
| clostridioides_difficile | `enterocolitis due to clostridium difficile` | keep | Explicit causative organism diagnosis |
| clostridioides_difficile | `enterocolitis due to c. difficile` | keep | Explicit causative organism diagnosis |
| clostridioides_difficile | `enterocolitis due to c difficile` | keep | Explicit causative organism diagnosis |
| clostridioides_difficile | `recurrent clostridioides difficile infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent clostridium difficile infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent c. difficile infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent c difficile infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent c. diff infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent c diff infection` | keep | Recurrent CDI diagnosis |
| clostridioides_difficile | `recurrent cdi` | keep | Recurrent CDI shorthand |
| clostridioides_difficile | `fulminant clostridioides difficile infection` | keep | Fulminant CDI diagnosis |
| clostridioides_difficile | `fulminant clostridium difficile infection` | keep | Fulminant CDI diagnosis |
| clostridioides_difficile | `fulminant c. difficile infection` | keep | Fulminant CDI diagnosis |
| clostridioides_difficile | `fulminant c difficile infection` | keep | Fulminant CDI diagnosis |
| clostridioides_difficile | `fulminant c. diff infection` | keep | Fulminant CDI diagnosis |
| clostridioides_difficile | `fulminant c diff infection` | keep | Fulminant CDI diagnosis |
| deep_vein_thrombosis | `deep vein thrombosis` | keep | Full diagnostic term |
| deep_vein_thrombosis | `deep venous thrombosis` | keep | Venous wording for DVT |
| deep_vein_thrombosis | `deep vein thrombus` | keep | Deep venous thrombus diagnosis |
| deep_vein_thrombosis | `deep venous thrombus` | keep | Venous thrombus diagnostic wording |
| deep_vein_thrombosis | `deep vein clot` | keep | Informal DVT wording |
| deep_vein_thrombosis | `deep venous clot` | keep | Informal venous DVT wording |
| deep_vein_thrombosis | `deep thrombophlebitis` | keep | Deep venous thrombosis synonym |
| deep_vein_thrombosis | `deep vein thrombophlebitis` | keep | Deep vein thrombosis synonym |
| deep_vein_thrombosis | `deep venous thrombophlebitis` | keep | Deep venous thrombosis synonym |
| deep_vein_thrombosis | `deep phlebothrombosis` | keep | Deep venous thrombosis synonym |
| deep_vein_thrombosis | `phlebothrombosis` | keep | Venous thrombosis diagnostic term |
| deep_vein_thrombosis | `dvt` | keep | Standard DVT abbreviation |
| deep_vein_thrombosis | `d.v.t.` | keep | Punctuated DVT abbreviation |
| deep_vein_thrombosis | `acute deep vein thrombosis` | keep | Acute DVT specification |
| deep_vein_thrombosis | `acute deep venous thrombosis` | keep | Acute venous DVT specification |
| deep_vein_thrombosis | `acute dvt` | keep | Acute DVT shorthand |
| deep_vein_thrombosis | `chronic deep vein thrombosis` | keep | Chronic DVT specification |
| deep_vein_thrombosis | `chronic deep venous thrombosis` | keep | Chronic venous DVT specification |
| deep_vein_thrombosis | `chronic dvt` | keep | Chronic DVT shorthand |
| deep_vein_thrombosis | `recurrent deep vein thrombosis` | keep | Recurrent DVT specification |
| deep_vein_thrombosis | `recurrent deep venous thrombosis` | keep | Recurrent venous DVT specification |
| deep_vein_thrombosis | `recurrent dvt` | keep | Recurrent DVT shorthand |
| deep_vein_thrombosis | `proximal deep vein thrombosis` | keep | Proximal DVT specification |
| deep_vein_thrombosis | `proximal deep venous thrombosis` | keep | Proximal venous DVT specification |
| deep_vein_thrombosis | `proximal dvt` | keep | Proximal DVT shorthand |
| deep_vein_thrombosis | `distal deep vein thrombosis` | keep | Distal DVT specification |
| deep_vein_thrombosis | `distal deep venous thrombosis` | keep | Distal venous DVT specification |
| deep_vein_thrombosis | `distal dvt` | keep | Distal DVT shorthand |
| deep_vein_thrombosis | `lower extremity deep vein thrombosis` | keep | Lower extremity DVT specification |
| deep_vein_thrombosis | `lower extremity deep venous thrombosis` | keep | Lower extremity venous DVT |
| deep_vein_thrombosis | `lower extremity dvt` | keep | Lower extremity DVT shorthand |
| deep_vein_thrombosis | `lower limb deep vein thrombosis` | keep | Lower limb DVT specification |
| deep_vein_thrombosis | `lower limb deep venous thrombosis` | keep | Lower limb venous DVT |
| deep_vein_thrombosis | `lower limb dvt` | keep | Lower limb DVT shorthand |
| deep_vein_thrombosis | `upper extremity deep vein thrombosis` | keep | Upper extremity DVT specification |
| deep_vein_thrombosis | `upper extremity deep venous thrombosis` | keep | Upper extremity venous DVT |
| deep_vein_thrombosis | `upper extremity dvt` | keep | Upper extremity DVT shorthand |
| deep_vein_thrombosis | `upper limb deep vein thrombosis` | keep | Upper limb DVT specification |
| deep_vein_thrombosis | `upper limb deep venous thrombosis` | keep | Upper limb venous DVT |
| deep_vein_thrombosis | `upper limb dvt` | keep | Upper limb DVT shorthand |
| deep_vein_thrombosis | `calf vein thrombosis` | keep | Calf deep venous thrombosis |
| deep_vein_thrombosis | `calf dvt` | keep | Calf DVT shorthand |
| deep_vein_thrombosis | `iliofemoral dvt` | keep | Iliofemoral DVT subtype |
| deep_vein_thrombosis | `femoropopliteal dvt` | keep | Femoropopliteal DVT subtype |
| dementia | `dementia` | keep | direct diagnosis term |
| dementia | `dementia syndrome` | keep | clinical dementia syndrome term |
| dementia | `dementing illness` | keep | clinical term for dementia |
| dementia | `major neurocognitive disorder` | keep | modern diagnostic synonym |
| dementia | `major cognitive disorder` | keep | clinical diagnostic synonym |
| dementia | `major ncd` | keep | abbreviation for major neurocognitive disorder |
| dementia | `mncd` | drop | ambiguous major versus mild disorder |
| dementia | `m.n.c.d.` | drop | ambiguous major versus mild disorder |
| dementia | `unspecified dementia` | keep | unspecified dementia diagnosis |
| dementia | `dementia nos` | keep | common unspecified dementia shorthand |
| dementia | `dementia n.o.s.` | keep | punctuation variant of dementia NOS |
| dementia | `dementia, unspecified` | keep | unspecified dementia wording |
| dementia | `senile dementia` | keep | historical dementia diagnosis term |
| dementia | `presenile dementia` | keep | historical early dementia term |
| dementia | `senility` | keep | historical dementia-related clinical term |
| dementia | `senile psychosis` | drop | broader psychosis category |
| dementia | `organic brain syndrome` | drop | may include non-dementia brain syndromes |
| dementia | `chronic organic brain syndrome` | keep | historical chronic dementia synonym |
| dementia | `organic mental syndrome` | drop | broad mental syndrome category |
| dementia | `primary degenerative dementia` | keep | degenerative dementia diagnosis |
| dementia | `degenerative dementia` | keep | dementia subtype description |
| dementia | `cortical dementia` | keep | dementia subtype description |
| dementia | `subcortical dementia` | keep | dementia subtype description |
| dementia | `progressive dementia` | keep | dementia progression descriptor |
| dementia | `early-onset dementia` | keep | early-onset dementia subtype |
| dementia | `young-onset dementia` | keep | young-onset dementia subtype |
| dementia | `late-onset dementia` | keep | late-onset dementia subtype |
| dementia | `mixed dementia` | keep | mixed dementia diagnosis |
| dementia | `dementia of the alzheimer type` | keep | Alzheimer-type dementia diagnosis |
| dementia | `dementia of alzheimer type` | keep | Alzheimer-type dementia diagnosis |
| dementia | `alzheimer-type dementia` | keep | Alzheimer-type dementia diagnosis |
| dementia | `alzheimer dementia` | keep | Alzheimer dementia diagnosis |
| dementia | `alzheimer's dementia` | keep | Alzheimer dementia diagnosis |
| dementia | `ad dementia` | keep | Alzheimer dementia abbreviation context |
| dementia | `d.a.t.` | drop | ambiguous direct antiglobulin test abbreviation |
| dementia | `dat` | drop | ambiguous direct antiglobulin test abbreviation |
| dementia | `sdat` | keep | senile Alzheimer dementia abbreviation |
| dementia | `s.d.a.t.` | keep | punctuation variant of SDAT |
| dementia | `pdat` | keep | presenile Alzheimer dementia abbreviation |
| dementia | `p.d.a.t.` | keep | punctuation variant of PDAT |
| dementia | `vascular dementia` | keep | vascular dementia diagnosis |
| dementia | `vad` | drop | ambiguous ventricular assist device abbreviation |
| dementia | `v.a.d.` | drop | ambiguous ventricular assist device abbreviation |
| dementia | `multi-infarct dementia` | keep | vascular dementia subtype |
| dementia | `multiinfarct dementia` | keep | vascular dementia subtype |
| dementia | `mid` | drop | ordinary word and ambiguous abbreviation |
| dementia | `m.i.d.` | keep | multi-infarct dementia abbreviation |
| dementia | `poststroke dementia` | keep | poststroke dementia diagnosis |
| dementia | `post-stroke dementia` | keep | poststroke dementia diagnosis |
| dementia | `arteriosclerotic dementia` | keep | vascular dementia diagnosis |
| dementia | `binswanger disease` | keep | subcortical vascular dementia condition |
| dementia | `lewy body dementia` | keep | Lewy body dementia diagnosis |
| dementia | `dementia with lewy bodies` | keep | Lewy body dementia diagnosis |
| dementia | `lbd` | keep | Lewy body dementia abbreviation |
| dementia | `l.b.d.` | keep | punctuation variant of LBD |
| dementia | `dlb` | drop | ambiguous lymphoma abbreviation |
| dementia | `d.l.b.` | drop | ambiguous lymphoma abbreviation |
| dementia | `frontotemporal dementia` | keep | frontotemporal dementia diagnosis |
| dementia | `fronto-temporal dementia` | keep | frontotemporal dementia diagnosis |
| dementia | `ftd` | keep | frontotemporal dementia abbreviation |
| dementia | `f.t.d.` | keep | punctuation variant of FTD |
| dementia | `behavioral variant frontotemporal dementia` | keep | frontotemporal dementia subtype |
| dementia | `bvftd` | keep | behavioral variant FTD abbreviation |
| dementia | `bv-ftd` | keep | behavioral variant FTD abbreviation |
| dementia | `pick disease` | keep | frontotemporal dementia condition |
| dementia | `pick's disease` | keep | frontotemporal dementia condition |
| dementia | `parkinson disease dementia` | keep | Parkinson disease dementia |
| dementia | `parkinson's dementia` | keep | Parkinson disease dementia |
| dementia | `parkinson dementia` | keep | Parkinson disease dementia |
| dementia | `pdd` | drop | ambiguous developmental disorder abbreviation |
| dementia | `p.d.d.` | drop | ambiguous developmental disorder abbreviation |
| dementia | `alcoholic dementia` | keep | alcohol-related dementia diagnosis |
| dementia | `alcohol-related dementia` | keep | alcohol-related dementia diagnosis |
| dementia | `alcohol-induced dementia` | keep | alcohol-related dementia diagnosis |
| dementia | `etoh-related dementia` | keep | alcohol-related dementia shorthand |
| dementia | `etoh dementia` | keep | alcohol-related dementia shorthand |
| dementia | `hiv-associated dementia` | keep | HIV-related dementia diagnosis |
| dementia | `hiv dementia` | keep | HIV-related dementia diagnosis |
| dementia | `had` | drop | ordinary word and ambiguous abbreviation |
| dementia | `h.a.d.` | keep | HIV-associated dementia abbreviation |
| dementia | `aids dementia complex` | keep | HIV dementia diagnosis |
| dementia | `adc` | drop | ambiguous imaging measurement abbreviation |
| dementia | `a.d.c.` | drop | ambiguous imaging measurement abbreviation |
| depression | `depression` | keep | core diagnosis term |
| depression | `clinical depression` | keep | common clinical diagnosis phrasing |
| depression | `depressive disorder` | keep | formal diagnostic category |
| depression | `depressive illness` | keep | clinical synonym for depression |
| depression | `major depression` | keep | common major depression term |
| depression | `major depressive disorder` | keep | formal major depression diagnosis |
| depression | `major depressive illness` | keep | clinical synonym for major depression |
| depression | `major depressive episode` | keep | major depression episode diagnosis |
| depression | `major depressive affective disorder` | keep | synonym for major depression |
| depression | `depressive episode` | keep | depression episode diagnosis term |
| depression | `unipolar depression` | keep | unipolar depressive illness term |
| depression | `unipolar disorder` | keep | shorthand for unipolar depression |
| depression | `unipolar affective disorder` | keep | unipolar depression diagnostic term |
| depression | `monopolar depression` | keep | synonym for unipolar depression |
| depression | `recurrent depression` | keep | recurrent depressive illness term |
| depression | `recurrent depressive disorder` | keep | formal recurrent depression diagnosis |
| depression | `single-episode depression` | keep | single depressive episode diagnosis |
| depression | `persistent depressive disorder` | keep | formal chronic depression diagnosis |
| depression | `dysthymic disorder` | keep | older dysthymia diagnostic term |
| depression | `dysthymia` | keep | persistent depressive disorder synonym |
| depression | `unspecified depression` | keep | unspecified depression diagnosis |
| depression | `unspecified depressive disorder` | keep | formal unspecified depression diagnosis |
| depression | `depressive disorder nos` | keep | NOS depressive disorder diagnosis |
| depression | `depression nos` | keep | NOS depression diagnosis |
| depression | `other specified depressive disorder` | keep | specified depressive disorder diagnosis |
| depression | `melancholia` | keep | melancholic depression clinical term |
| depression | `melancholic depression` | keep | depression with melancholic features |
| depression | `involutional melancholia` | keep | historical depressive disorder term |
| depression | `neurotic depression` | keep | historical depression diagnostic term |
| depression | `depressive neurosis` | keep | historical depressive disorder term |
| depression | `reactive depression` | keep | depression subtype clinical term |
| depression | `endogenous depression` | keep | historical depression subtype term |
| depression | `atypical depression` | keep | depression subtype clinical term |
| depression | `psychotic depression` | keep | depression with psychotic features |
| depression | `masked depression` | keep | historical depression presentation term |
| depression | `treatment-resistant depression` | keep | treatment-resistant depression diagnosis |
| depression | `postpartum depression` | keep | peripartum depression diagnosis |
| depression | `postnatal depression` | keep | postpartum depression synonym |
| depression | `antenatal depression` | keep | depression during pregnancy term |
| depression | `seasonal depression` | keep | seasonal depression subtype term |
| depression | `geriatric depression` | keep | depression in older adults |
| depression | `mdd` | keep | major depressive disorder abbreviation |
| depression | `m.d.d.` | keep | major depressive disorder abbreviation |
| depression | `mde` | keep | major depressive episode abbreviation |
| depression | `m.d.e.` | keep | major depressive episode abbreviation |
| depression | `trd` | keep | treatment-resistant depression abbreviation |
| diabetes_mellitus | `diabetes mellitus` | keep | canonical diagnosis name |
| diabetes_mellitus | `diabetes` | keep | common clinical shorthand |
| diabetes_mellitus | `dm` | drop | ambiguous with dermatomyositis |
| diabetes_mellitus | `d.m.` | drop | ambiguous with dermatomyositis |
| diabetes_mellitus | `sugar diabetes` | keep | established informal diabetes term |
| diabetes_mellitus | `type 1 diabetes mellitus` | keep | type 1 diabetes diagnosis |
| diabetes_mellitus | `type 1 diabetes` | keep | common type 1 shorthand |
| diabetes_mellitus | `type 1 dm` | keep | type 1 diabetes shorthand |
| diabetes_mellitus | `type i diabetes mellitus` | keep | roman numeral type variant |
| diabetes_mellitus | `type i diabetes` | keep | roman numeral type shorthand |
| diabetes_mellitus | `type i dm` | keep | roman numeral diabetes shorthand |
| diabetes_mellitus | `diabetes mellitus type 1` | keep | alternate type 1 ordering |
| diabetes_mellitus | `diabetes type 1` | keep | alternate type 1 ordering |
| diabetes_mellitus | `t1dm` | keep | standard type 1 abbreviation |
| diabetes_mellitus | `t1 dm` | keep | spaced type 1 abbreviation |
| diabetes_mellitus | `t1-dm` | keep | hyphenated type 1 abbreviation |
| diabetes_mellitus | `t1d` | keep | standard type 1 abbreviation |
| diabetes_mellitus | `dm1` | drop | ambiguous with myotonic dystrophy |
| diabetes_mellitus | `dm 1` | drop | ambiguous with myotonic dystrophy |
| diabetes_mellitus | `dm-1` | drop | ambiguous with myotonic dystrophy |
| diabetes_mellitus | `dm i` | keep | type 1 diabetes notation |
| diabetes_mellitus | `dm-i` | keep | type 1 diabetes notation |
| diabetes_mellitus | `insulin-dependent diabetes mellitus` | keep | established type 1 term |
| diabetes_mellitus | `insulin dependent diabetes mellitus` | keep | established type 1 term |
| diabetes_mellitus | `insulin-dependent diabetes` | keep | insulin-dependent diabetes term |
| diabetes_mellitus | `insulin dependent diabetes` | keep | insulin-dependent diabetes term |
| diabetes_mellitus | `iddm` | keep | standard insulin-dependent abbreviation |
| diabetes_mellitus | `i.d.d.m.` | keep | punctuated insulin-dependent abbreviation |
| diabetes_mellitus | `juvenile diabetes` | keep | established type 1 synonym |
| diabetes_mellitus | `juvenile-onset diabetes` | keep | type 1 onset descriptor |
| diabetes_mellitus | `juvenile-onset diabetes mellitus` | keep | type 1 onset descriptor |
| diabetes_mellitus | `brittle diabetes` | keep | diabetes phenotype descriptor |
| diabetes_mellitus | `type 2 diabetes mellitus` | keep | type 2 diabetes diagnosis |
| diabetes_mellitus | `type 2 diabetes` | keep | common type 2 shorthand |
| diabetes_mellitus | `type 2 dm` | keep | type 2 diabetes shorthand |
| diabetes_mellitus | `type ii diabetes mellitus` | keep | roman numeral type variant |
| diabetes_mellitus | `type ii diabetes` | keep | roman numeral type shorthand |
| diabetes_mellitus | `type ii dm` | keep | roman numeral diabetes shorthand |
| diabetes_mellitus | `diabetes mellitus type 2` | keep | alternate type 2 ordering |
| diabetes_mellitus | `diabetes type 2` | keep | alternate type 2 ordering |
| diabetes_mellitus | `t2dm` | keep | standard type 2 abbreviation |
| diabetes_mellitus | `t2 dm` | keep | spaced type 2 abbreviation |
| diabetes_mellitus | `t2-dm` | keep | hyphenated type 2 abbreviation |
| diabetes_mellitus | `t2d` | keep | standard type 2 abbreviation |
| diabetes_mellitus | `dm2` | keep | type 2 diabetes abbreviation |
| diabetes_mellitus | `dm 2` | keep | type 2 diabetes abbreviation |
| diabetes_mellitus | `dm-2` | keep | type 2 diabetes abbreviation |
| diabetes_mellitus | `dm ii` | keep | type 2 diabetes notation |
| diabetes_mellitus | `dm-ii` | keep | type 2 diabetes notation |
| diabetes_mellitus | `non-insulin-dependent diabetes mellitus` | keep | established type 2 term |
| diabetes_mellitus | `non-insulin dependent diabetes mellitus` | keep | established type 2 term |
| diabetes_mellitus | `non-insulin-dependent diabetes` | keep | non-insulin-dependent diabetes term |
| diabetes_mellitus | `non-insulin dependent diabetes` | keep | non-insulin-dependent diabetes term |
| diabetes_mellitus | `niddm` | keep | standard type 2 abbreviation |
| diabetes_mellitus | `n.i.d.d.m.` | keep | punctuated type 2 abbreviation |
| diabetes_mellitus | `adult-onset diabetes` | keep | established type 2 synonym |
| diabetes_mellitus | `adult-onset diabetes mellitus` | keep | established type 2 synonym |
| diabetes_mellitus | `gestational diabetes mellitus` | keep | gestational diabetes diagnosis |
| diabetes_mellitus | `gestational diabetes` | keep | gestational diabetes shorthand |
| diabetes_mellitus | `gdm` | keep | standard gestational diabetes abbreviation |
| diabetes_mellitus | `g.d.m.` | keep | punctuated gestational diabetes abbreviation |
| diabetes_mellitus | `maturity-onset diabetes of the young` | keep | monogenic diabetes subtype |
| diabetes_mellitus | `maturity onset diabetes of the young` | keep | monogenic diabetes subtype |
| diabetes_mellitus | `mody` | keep | standard monogenic diabetes abbreviation |
| diabetes_mellitus | `monogenic diabetes` | keep | monogenic diabetes diagnosis |
| diabetes_mellitus | `neonatal diabetes mellitus` | keep | neonatal diabetes subtype |
| diabetes_mellitus | `neonatal diabetes` | keep | neonatal diabetes subtype |
| diabetes_mellitus | `ndm` | keep | neonatal diabetes abbreviation |
| diabetes_mellitus | `latent autoimmune diabetes in adults` | keep | autoimmune diabetes subtype |
| diabetes_mellitus | `lada` | keep | standard autoimmune diabetes abbreviation |
| diabetes_mellitus | `type 1.5 diabetes` | keep | LADA informal synonym |
| diabetes_mellitus | `type 1.5 diabetes mellitus` | keep | LADA informal synonym |
| diabetes_mellitus | `secondary diabetes mellitus` | keep | secondary diabetes diagnosis |
| diabetes_mellitus | `secondary diabetes` | keep | secondary diabetes shorthand |
| diabetes_mellitus | `diabetes due to an underlying condition` | keep | etiologic diabetes designation |
| diabetes_mellitus | `drug-induced diabetes mellitus` | keep | drug-induced diabetes diagnosis |
| diabetes_mellitus | `drug-induced diabetes` | keep | drug-induced diabetes shorthand |
| diabetes_mellitus | `steroid-induced diabetes mellitus` | keep | steroid-induced diabetes diagnosis |
| diabetes_mellitus | `steroid-induced diabetes` | keep | steroid-induced diabetes shorthand |
| diabetes_mellitus | `pancreatogenic diabetes mellitus` | keep | pancreatogenic diabetes diagnosis |
| diabetes_mellitus | `pancreatogenic diabetes` | keep | pancreatogenic diabetes shorthand |
| diabetes_mellitus | `pancreatic diabetes` | keep | pancreatogenic diabetes synonym |
| diabetes_mellitus | `type 3c diabetes mellitus` | keep | type 3c diabetes subtype |
| diabetes_mellitus | `type 3c diabetes` | keep | type 3c diabetes subtype |
| diabetes_mellitus | `cystic fibrosis-related diabetes mellitus` | keep | cystic fibrosis diabetes subtype |
| diabetes_mellitus | `cystic fibrosis-related diabetes` | keep | cystic fibrosis diabetes subtype |
| diabetes_mellitus | `cf-related diabetes` | keep | cystic fibrosis diabetes shorthand |
| diabetes_mellitus | `postpancreatectomy diabetes mellitus` | keep | postpancreatectomy diabetes diagnosis |
| diabetes_mellitus | `postpancreatectomy diabetes` | keep | postpancreatectomy diabetes shorthand |
| diabetes_mellitus | `post-transplantation diabetes mellitus` | keep | post-transplant diabetes diagnosis |
| diabetes_mellitus | `post-transplantation diabetes` | keep | post-transplant diabetes shorthand |
| diabetes_mellitus | `ptdm` | keep | standard post-transplant abbreviation |
| diabetes_mellitus | `malnutrition-related diabetes mellitus` | keep | malnutrition-related diabetes diagnosis |
| diabetes_mellitus | `malnutrition-related diabetes` | keep | malnutrition-related diabetes shorthand |
| diabetes_mellitus | `mr dm` | keep | malnutrition-related diabetes abbreviation |
| diabetes_mellitus | `mr-dm` | keep | malnutrition-related diabetes abbreviation |
| dyspnea | `dyspnea` | keep | standard diagnosis term |
| dyspnea | `dyspnoea` | keep | British spelling variant |
| dyspnea | `shortness of breath` | keep | common clinical synonym |
| dyspnea | `sob` | keep | common clinical abbreviation |
| dyspnea | `s.o.b.` | keep | punctuation abbreviation variant |
| dyspnea | `breathlessness` | keep | common clinical synonym |
| dyspnea | `difficulty breathing` | keep | common descriptive synonym |
| dyspnea | `breathing difficulty` | keep | common descriptive synonym |
| dyspnea | `labored breathing` | keep | clinical description of dyspnea |
| dyspnea | `laborious breathing` | keep | clinical description of dyspnea |
| dyspnea | `air hunger` | keep | common dyspnea descriptor |
| dyspnea | `exertional dyspnea` | keep | dyspnea qualifying subtype |
| dyspnea | `dyspnea on exertion` | keep | common exertional dyspnea phrasing |
| dyspnea | `doe` | keep | common clinical abbreviation |
| dyspnea | `d.o.e.` | keep | punctuation abbreviation variant |
| dyspnea | `shortness of breath on exertion` | keep | common exertional dyspnea phrasing |
| dyspnea | `exertional shortness of breath` | keep | common exertional dyspnea phrasing |
| dyspnea | `paroxysmal nocturnal dyspnea` | drop | distinct positional dyspnea subtype |
| dyspnea | `pnd` | drop | ambiguous abbreviation and distinct subtype |
| dyspnea | `p.n.d.` | drop | ambiguous abbreviation and distinct subtype |
| dyspnea | `nocturnal dyspnea` | drop | distinct nocturnal dyspnea subtype |
| dyspnea | `orthopnea` | drop | distinct positional dyspnea subtype |
| dyspnea | `orthopnoea` | drop | distinct positional dyspnea subtype |
| dyspnea | `platypnea` | drop | distinct positional dyspnea subtype |
| dyspnea | `platypnoea` | drop | distinct positional dyspnea subtype |
| dyspnea | `trepopnea` | drop | distinct positional dyspnea subtype |
| dyspnea | `trepopnoea` | drop | distinct positional dyspnea subtype |
| fever | `fever` | keep | Direct diagnosis term |
| fever | `pyrexia` | keep | Clinical synonym for fever |
| fever | `febrile illness` | keep | Common clinical fever diagnosis |
| fever | `acute febrile illness` | keep | Specific acute fever presentation |
| fever | `febrile syndrome` | keep | Clinical syndrome naming fever |
| fever | `febrile` | keep | Common shorthand for fever |
| fever | `elevated temperature` | keep | Clinical description of fever |
| fever | `elevated temp` | keep | Common abbreviated fever description |
| fever | `fever unspecified` | keep | Unspecified fever diagnosis |
| fever | `unspecified fever` | keep | Unspecified fever diagnosis wording |
| fever | `fever nos` | keep | Fever not otherwise specified |
| fever | `fever n.o.s.` | keep | Fever not otherwise specified |
| fever | `pyrexia nos` | keep | Pyrexia not otherwise specified |
| fever | `pyrexia n.o.s.` | keep | Pyrexia not otherwise specified |
| fever | `fever of unknown origin` | keep | Recognized fever diagnostic category |
| fever | `pyrexia of unknown origin` | keep | Synonymous unknown-origin fever category |
| fever | `fever of unknown etiology` | keep | Unknown-cause fever diagnosis |
| fever | `fever of undetermined origin` | keep | Unknown-origin fever diagnosis |
| fever | `fuo` | keep | Standard fever abbreviation |
| fever | `f.u.o.` | keep | Punctuated FUO abbreviation |
| fever | `puo` | keep | Pyrexia unknown origin abbreviation |
| fever | `p.u.o.` | keep | Punctuated PUO abbreviation |
| fever | `hyperpyrexia` | keep | Severe elevated fever diagnosis |
| fever | `neutropenic fever` | keep | Fever diagnosis with neutropenia |
| fever | `febrile neutropenia` | keep | Synonymous neutropenic fever diagnosis |
| fever | `tumor fever` | keep | Malignancy-associated fever diagnosis |
| fever | `tumour fever` | keep | Malignancy-associated fever diagnosis |
| fever | `drug fever` | keep | Medication-associated fever diagnosis |
| fever | `postoperative fever` | keep | Post-surgical fever diagnosis |
| fever | `post-operative fever` | keep | Post-surgical fever diagnosis variant |
| fever | `central fever` | keep | Central nervous system fever |
| fever | `relapsing fever` | keep | Recognized recurrent fever pattern |
| fever | `remittent fever` | keep | Recognized fever pattern diagnosis |
| fever | `intermittent fever` | keep | Recognized fever pattern diagnosis |
| fever | `continuous fever` | keep | Recognized fever pattern diagnosis |
| fever | `saddleback fever` | keep | Recognized fever pattern diagnosis |
| fever | `pel-ebstein fever` | keep | Named fever pattern diagnosis |
| fever | `viral fever` | keep | Viral-associated fever diagnosis |
| fever | `bacterial fever` | keep | Bacterial-associated fever diagnosis |
| fever | `infectious fever` | keep | Infection-associated fever diagnosis |
| heart_failure | `heart failure` | keep | Core diagnosis term |
| heart_failure | `cardiac failure` | keep | Common synonym for heart failure |
| heart_failure | `congestive heart failure` | keep | Standard heart failure term |
| heart_failure | `congestive cardiac failure` | keep | Common clinical synonym |
| heart_failure | `congestive failure` | keep | Elliptical congestive heart failure term |
| heart_failure | `cardiac insufficiency` | keep | Clinical synonym for heart failure |
| heart_failure | `heart insufficiency` | keep | Clinical synonym for heart failure |
| heart_failure | `myocardial failure` | keep | Synonym describing failed myocardium |
| heart_failure | `cardiac decompensation` | keep | Common heart failure presentation |
| heart_failure | `heart failure syndrome` | keep | Recognized heart failure syndrome |
| heart_failure | `ventricular failure` | keep | Heart failure involving ventricles |
| heart_failure | `cardiac pump failure` | keep | Descriptive synonym for heart failure |
| heart_failure | `hf` | keep | Standard heart failure abbreviation |
| heart_failure | `h.f.` | keep | Punctuated heart failure abbreviation |
| heart_failure | `chf` | keep | Standard congestive heart failure abbreviation |
| heart_failure | `c.h.f.` | keep | Punctuated congestive heart failure abbreviation |
| heart_failure | `ccf` | keep | Standard congestive cardiac failure abbreviation |
| heart_failure | `c.c.f.` | keep | Punctuated congestive cardiac failure abbreviation |
| heart_failure | `acute heart failure` | keep | Acute heart failure subtype |
| heart_failure | `acute cardiac failure` | keep | Acute heart failure synonym |
| heart_failure | `acute congestive heart failure` | keep | Acute congestive heart failure subtype |
| heart_failure | `acute decompensated heart failure` | keep | Standard acute decompensation term |
| heart_failure | `acute decompensated congestive heart failure` | keep | Acute decompensated CHF subtype |
| heart_failure | `acute decompensated cardiac failure` | keep | Acute decompensated cardiac failure |
| heart_failure | `acute heart failure syndrome` | keep | Acute heart failure syndrome |
| heart_failure | `adhf` | keep | Standard acute decompensated HF abbreviation |
| heart_failure | `a.d.h.f.` | keep | Punctuated ADHF abbreviation |
| heart_failure | `chronic heart failure` | keep | Chronic heart failure subtype |
| heart_failure | `chronic congestive heart failure` | keep | Chronic congestive heart failure subtype |
| heart_failure | `chronic cardiac failure` | keep | Chronic cardiac failure synonym |
| heart_failure | `acute-on-chronic heart failure` | keep | Acute-on-chronic heart failure subtype |
| heart_failure | `acute on chronic heart failure` | keep | Acute-on-chronic heart failure subtype |
| heart_failure | `acute-on-chronic congestive heart failure` | keep | Acute-on-chronic CHF subtype |
| heart_failure | `acute on chronic congestive heart failure` | keep | Acute-on-chronic CHF subtype |
| heart_failure | `decompensated heart failure` | keep | Decompensated heart failure subtype |
| heart_failure | `decompensated congestive heart failure` | keep | Decompensated CHF subtype |
| heart_failure | `decompensated cardiac failure` | keep | Decompensated cardiac failure synonym |
| heart_failure | `heart failure exacerbation` | keep | Heart failure worsening episode |
| heart_failure | `chf exacerbation` | keep | CHF worsening episode |
| heart_failure | `systolic heart failure` | keep | Systolic heart failure subtype |
| heart_failure | `systolic cardiac failure` | keep | Systolic heart failure synonym |
| heart_failure | `systolic congestive heart failure` | keep | Systolic CHF subtype |
| heart_failure | `diastolic heart failure` | keep | Diastolic heart failure subtype |
| heart_failure | `diastolic cardiac failure` | keep | Diastolic heart failure synonym |
| heart_failure | `diastolic congestive heart failure` | keep | Diastolic CHF subtype |
| heart_failure | `combined systolic and diastolic heart failure` | keep | Combined heart failure subtype |
| heart_failure | `heart failure with reduced ejection fraction` | keep | Standard reduced EF heart failure |
| heart_failure | `heart failure with mid-range ejection fraction` | keep | Standard mid-range EF heart failure |
| heart_failure | `heart failure with preserved ejection fraction` | keep | Standard preserved EF heart failure |
| heart_failure | `heart failure with improved ejection fraction` | keep | Standard improved EF heart failure |
| heart_failure | `heart failure with recovered ejection fraction` | keep | Recovered EF heart failure subtype |
| heart_failure | `hfref` | keep | Standard HFrEF abbreviation |
| heart_failure | `hfmr ef` | keep | Mid-range EF abbreviation variant |
| heart_failure | `hfmref` | keep | Standard HFmrEF abbreviation |
| heart_failure | `hfpef` | keep | Standard HFpEF abbreviation |
| heart_failure | `hfimpef` | keep | Standard HFimpEF abbreviation |
| heart_failure | `hfrecef` | keep | Recovered EF HF abbreviation |
| heart_failure | `right heart failure` | keep | Right-sided heart failure subtype |
| heart_failure | `right-sided heart failure` | keep | Right heart failure synonym |
| heart_failure | `right ventricular failure` | keep | Right-sided heart failure subtype |
| heart_failure | `left heart failure` | keep | Left-sided heart failure subtype |
| heart_failure | `left-sided heart failure` | keep | Left heart failure synonym |
| heart_failure | `left ventricular failure` | keep | Left-sided heart failure subtype |
| heart_failure | `biventricular heart failure` | keep | Biventricular heart failure subtype |
| heart_failure | `biventricular failure` | keep | Biventricular heart failure synonym |
| heart_failure | `high-output heart failure` | keep | High-output heart failure subtype |
| heart_failure | `high-output cardiac failure` | keep | High-output heart failure synonym |
| heart_failure | `low-output heart failure` | keep | Low-output heart failure subtype |
| heart_failure | `low-output cardiac failure` | keep | Low-output heart failure synonym |
| heart_failure | `advanced heart failure` | keep | Advanced heart failure stage |
| heart_failure | `end-stage heart failure` | keep | End-stage heart failure stage |
| heart_failure | `end stage heart failure` | keep | End-stage heart failure stage |
| heart_failure | `refractory heart failure` | keep | Refractory heart failure subtype |
| heart_failure | `terminal heart failure` | keep | Terminal heart failure stage |
| hfpef | `heart failure with preserved ejection fraction` | keep | Exact diagnosis name |
| hfpef | `heart failure with preserved ef` | keep | Common abbreviated diagnosis wording |
| hfpef | `heart failure with preserved systolic function` | keep | Synonym emphasizing preserved systole |
| hfpef | `heart failure with normal ejection fraction` | keep | Common HFpEF synonym |
| hfpef | `heart failure with normal ef` | keep | Abbreviated normal EF synonym |
| hfpef | `heart failure with normal systolic function` | keep | Synonym emphasizing normal systole |
| hfpef | `preserved ejection fraction heart failure` | keep | Reordered diagnosis wording |
| hfpef | `preserved ef heart failure` | keep | Reordered abbreviated wording |
| hfpef | `hf with preserved ejection fraction` | keep | Common HF abbreviation |
| hfpef | `hf with preserved ef` | keep | Common abbreviated HF wording |
| hfpef | `hf with preserved systolic function` | keep | HF shorthand with preserved systole |
| hfpef | `hfpef` | keep | Standard HFpEF abbreviation |
| hfpef | `hf-pef` | keep | Punctuation variant abbreviation |
| hfpef | `hfnef` | keep | HF with normal EF abbreviation |
| hfpef | `hf-nef` | keep | Punctuation variant abbreviation |
| hfpef | `hfpsf` | keep | HF preserved systolic function abbreviation |
| hfpef | `hf-psf` | keep | Punctuation variant abbreviation |
| hfpef | `diastolic heart failure` | keep | Established HFpEF clinical term |
| hfpef | `diastolic hf` | keep | Common abbreviated clinical term |
| hfpef | `diastolic congestive heart failure` | keep | Diastolic HF terminology |
| hfpef | `congestive diastolic heart failure` | keep | Reordered diastolic HF terminology |
| hfpef | `diastolic chf` | keep | Common diastolic CHF abbreviation |
| hfpef | `dchf` | keep | Diastolic congestive heart failure abbreviation |
| hfpef | `dhf` | keep | Diastolic heart failure abbreviation |
| hfpef | `chf with preserved ejection fraction` | keep | CHF wording with preserved EF |
| hfpef | `chf with preserved ef` | keep | Abbreviated CHF preserved EF wording |
| hfpef | `acute diastolic heart failure` | keep | Acute HFpEF presentation |
| hfpef | `chronic diastolic heart failure` | keep | Chronic HFpEF presentation |
| hfpef | `acute on chronic diastolic heart failure` | keep | Acute-on-chronic HFpEF presentation |
| hfpef | `acute diastolic congestive heart failure` | keep | Acute diastolic CHF terminology |
| hfpef | `chronic diastolic congestive heart failure` | keep | Chronic diastolic CHF terminology |
| hfref | `heart failure with reduced ejection fraction` | keep | Exact diagnosis name |
| hfref | `heart failure with reduced ef` | keep | Common abbreviated diagnosis wording |
| hfref | `heart failure with low ejection fraction` | keep | Equivalent low EF wording |
| hfref | `heart failure with depressed ejection fraction` | keep | Equivalent depressed EF wording |
| hfref | `heart failure with impaired ejection fraction` | keep | Equivalent impaired EF wording |
| hfref | `heart failure with decreased ejection fraction` | keep | Equivalent decreased EF wording |
| hfref | `reduced ejection fraction heart failure` | keep | Reordered diagnosis wording |
| hfref | `reduced ef heart failure` | keep | Reordered abbreviated diagnosis wording |
| hfref | `low ejection fraction heart failure` | keep | Reordered low EF wording |
| hfref | `low ef heart failure` | keep | Reordered abbreviated EF wording |
| hfref | `systolic heart failure` | keep | Established HFrEF synonym |
| hfref | `systolic hf` | keep | Common systolic heart failure abbreviation |
| hfref | `systolic congestive heart failure` | keep | Established systolic heart failure synonym |
| hfref | `systolic chf` | keep | Common systolic CHF abbreviation |
| hfref | `chf with reduced ef` | keep | CHF phenotype specified by reduced EF |
| hfref | `heart failure with systolic dysfunction` | keep | Equivalent systolic dysfunction wording |
| hfref | `left ventricular systolic dysfunction` | drop | May occur without clinical heart failure |
| hfref | `lv systolic dysfunction` | drop | May occur without clinical heart failure |
| hfref | `hfref` | keep | Standard HFrEF abbreviation |
| hfref | `hf-ref` | keep | Punctuation variant of HFrEF |
| hfref | `hf ref` | keep | Spacing variant of HFrEF |
| hfref | `hfr ef` | keep | Spacing variant of HFrEF |
| hfref | `acute systolic heart failure` | keep | Acute presentation of target diagnosis |
| hfref | `acute on chronic systolic heart failure` | keep | Acute chronic target diagnosis |
| hfref | `chronic systolic heart failure` | keep | Chronic presentation of target diagnosis |
| hfref | `acute systolic chf` | keep | Acute systolic CHF wording |
| hfref | `acute on chronic systolic chf` | keep | Acute chronic systolic CHF wording |
| hfref | `chronic systolic chf` | keep | Chronic systolic CHF wording |
| hfref | `acute decompensated hfr ef` | keep | Decompensated target diagnosis |
| hfref | `acute decompensated systolic heart failure` | keep | Decompensated systolic heart failure |
| hypertension | `hypertension` | keep | standard diagnosis term |
| hypertension | `htn` | keep | common clinical abbreviation |
| hypertension | `hbp` | keep | common shorthand for hypertension |
| hypertension | `high blood pressure` | keep | plain-language diagnosis term |
| hypertension | `arterial hypertension` | keep | standard hypertension terminology |
| hypertension | `systemic hypertension` | keep | standard hypertension terminology |
| hypertension | `systemic arterial hypertension` | keep | standard hypertension terminology |
| hypertension | `essential hypertension` | keep | common primary hypertension subtype |
| hypertension | `primary hypertension` | keep | common hypertension subtype |
| hypertension | `idiopathic hypertension` | keep | hypertension without identified cause |
| hypertension | `secondary hypertension` | keep | recognized hypertension subtype |
| hypertension | `benign hypertension` | keep | recognized hypertension classification |
| hypertension | `malignant hypertension` | keep | severe hypertension subtype |
| hypertension | `chronic hypertension` | keep | common chronic diagnosis wording |
| hypertension | `resistant hypertension` | keep | recognized difficult-to-control hypertension |
| hypertension | `refractory hypertension` | keep | recognized treatment-resistant hypertension |
| hypertension | `white coat hypertension` | keep | recognized hypertension phenotype |
| hypertension | `isolated systolic hypertension` | keep | recognized hypertension subtype |
| hypertension | `isolated diastolic hypertension` | keep | recognized hypertension subtype |
| hypertension | `accelerated hypertension` | keep | recognized severe hypertension subtype |
| metastatic_cancer | `metastatic malignant neoplasm` | keep | Exact diagnosis term |
| metastatic_cancer | `metastatic malignancy` | keep | Common oncologic diagnosis wording |
| metastatic_cancer | `metastatic cancer` | keep | Common oncologic diagnosis wording |
| metastatic_cancer | `metastatic carcinoma` | keep | Metastatic epithelial cancer diagnosis |
| metastatic_cancer | `metastatic neoplasm` | keep | Common diagnosis shorthand |
| metastatic_cancer | `metastatic disease` | keep | Common oncology shorthand |
| metastatic_cancer | `metastatic tumor` | keep | Common oncologic diagnosis wording |
| metastatic_cancer | `metastatic ca` | keep | Cancer shorthand in notes |
| metastatic_cancer | `met ca` | keep | Common metastatic cancer shorthand |
| metastatic_cancer | `metastases` | keep | Plural metastatic disease term |
| metastatic_cancer | `metastasis` | keep | Metastatic spread diagnosis term |
| metastatic_cancer | `mets` | keep | Common clinician shorthand |
| metastatic_cancer | `secondary malignant neoplasm` | keep | Coding term for metastasis |
| metastatic_cancer | `secondary malignancy` | keep | Common term for metastatic cancer |
| metastatic_cancer | `secondary cancer` | keep | Common term for metastatic cancer |
| metastatic_cancer | `secondary carcinoma` | keep | Secondary metastatic carcinoma term |
| metastatic_cancer | `secondary neoplasm` | keep | Secondary metastatic neoplasm term |
| metastatic_cancer | `secondary tumor` | keep | Secondary metastatic tumor term |
| metastatic_cancer | `disseminated malignant neoplasm` | keep | Disseminated cancer diagnosis wording |
| metastatic_cancer | `disseminated malignancy` | keep | Disseminated cancer diagnosis wording |
| metastatic_cancer | `disseminated cancer` | keep | Disseminated cancer diagnosis wording |
| metastatic_cancer | `disseminated carcinoma` | keep | Disseminated carcinoma diagnosis wording |
| metastatic_cancer | `disseminated neoplasm` | keep | Disseminated neoplasm diagnosis wording |
| metastatic_cancer | `disseminated tumor` | keep | Disseminated tumor diagnosis wording |
| metastatic_cancer | `malignant neoplasm with metastases` | keep | Explicit metastatic malignancy wording |
| metastatic_cancer | `cancer with metastases` | keep | Explicit metastatic cancer wording |
| metastatic_cancer | `carcinoma with metastases` | keep | Explicit metastatic carcinoma wording |
| metastatic_cancer | `cancer metastatic` | keep | Elliptical metastatic cancer wording |
| metastatic_cancer | `carcinoma metastatic` | keep | Elliptical metastatic carcinoma wording |
| metastatic_cancer | `metastatic` | keep | Common oncology shorthand |
| metastatic_cancer | `mnbrian?` | drop | Not recognizable diagnostic term |
| obesity | `obesity` | keep | Direct diagnosis term |
| obesity | `obese` | keep | Common diagnostic adjective |
| obesity | `obes.` | keep | Clinical abbreviation for obesity |
| obesity | `adiposity` | keep | Clinical term for obesity |
| obesity | `morbid obesity` | keep | Established obesity severity term |
| obesity | `morbidly obese` | keep | Common diagnostic adjective |
| obesity | `severe obesity` | keep | Established obesity severity term |
| obesity | `severely obese` | keep | Common diagnostic adjective |
| obesity | `clinically severe obesity` | keep | Obesity severity designation |
| obesity | `extreme obesity` | keep | Established obesity severity term |
| obesity | `super obesity` | keep | Extreme obesity classification |
| obesity | `class i obesity` | keep | Obesity class designation |
| obesity | `class ii obesity` | keep | Obesity class designation |
| obesity | `class iii obesity` | keep | Obesity class designation |
| obesity | `class 1 obesity` | keep | Obesity class designation |
| obesity | `class 2 obesity` | keep | Obesity class designation |
| obesity | `class 3 obesity` | keep | Obesity class designation |
| obesity | `primary obesity` | keep | Obesity etiologic designation |
| obesity | `secondary obesity` | keep | Obesity etiologic designation |
| obesity | `simple obesity` | keep | Established obesity subtype |
| obesity | `exogenous obesity` | keep | Obesity etiologic subtype |
| obesity | `endogenous obesity` | keep | Obesity etiologic subtype |
| obesity | `constitutional obesity` | keep | Obesity etiologic subtype |
| obesity | `nutritional obesity` | keep | Obesity etiologic subtype |
| obesity | `caloric obesity` | keep | Obesity etiologic subtype |
| obesity | `obesity due to excess calories` | keep | Specific obesity diagnosis |
| obesity | `other obesity due to excess calories` | keep | Specific obesity diagnosis |
| obesity | `drug-induced obesity` | keep | Specific obesity diagnosis |
| obesity | `morbid obesity due to excess calories` | keep | Specific obesity diagnosis |
| obesity | `generalized obesity` | keep | Obesity distribution subtype |
| obesity | `central obesity` | keep | Obesity distribution subtype |
| obesity | `abdominal obesity` | keep | Obesity distribution subtype |
| obesity | `visceral obesity` | keep | Obesity distribution subtype |
| obesity | `truncal obesity` | keep | Obesity distribution subtype |
| obesity | `android obesity` | keep | Obesity distribution subtype |
| obesity | `gynoid obesity` | keep | Obesity distribution subtype |
| obesity | `hypertrophic obesity` | keep | Obesity adipocyte subtype |
| obesity | `hyperplastic obesity` | keep | Obesity adipocyte subtype |
| obesity | `morbid adiposity` | keep | Clinical obesity synonym |
| obesity | `adiposity-based chronic disease` | keep | Obesity disease terminology |
| obesity | `abcd` | drop | Ambiguous clinical abbreviation |
| obesity | `mo` | drop | Ambiguous clinical abbreviation |
| obesity | `m.o.` | drop | Ambiguous clinical abbreviation |
| obesity | `obesity nos` | keep | Unspecified obesity diagnosis |
| obesity | `obesity, unspecified` | keep | Unspecified obesity diagnosis |
| pulmonary_embolism | `pulmonary embolism` | keep | standard diagnosis name |
| pulmonary_embolism | `pulmonary embolus` | keep | standard singular synonym |
| pulmonary_embolism | `pulmonary emboli` | keep | standard plural synonym |
| pulmonary_embolism | `pulmonary thromboembolism` | keep | standard diagnostic synonym |
| pulmonary_embolism | `pulmonary thromboembolus` | keep | standard singular synonym |
| pulmonary_embolism | `pulmonary thromboemboli` | keep | standard plural synonym |
| pulmonary_embolism | `pulmonary artery embolism` | keep | pulmonary artery diagnosis synonym |
| pulmonary_embolism | `pulmonary arterial embolism` | keep | pulmonary artery diagnosis synonym |
| pulmonary_embolism | `pulmonary artery thromboembolism` | keep | pulmonary artery thrombotic synonym |
| pulmonary_embolism | `pulmonary arterial thromboembolism` | keep | pulmonary artery thrombotic synonym |
| pulmonary_embolism | `pulmonary embolic disease` | keep | clinical diagnostic phrasing |
| pulmonary_embolism | `pulmonary embolic event` | keep | clinical diagnostic phrasing |
| pulmonary_embolism | `pulm embolism` | keep | common abbreviated diagnosis |
| pulmonary_embolism | `pulm embolus` | keep | common abbreviated diagnosis |
| pulmonary_embolism | `pulm emboli` | keep | common abbreviated plural |
| pulmonary_embolism | `lung embolism` | keep | informal diagnostic synonym |
| pulmonary_embolism | `lung embolus` | keep | informal diagnostic synonym |
| pulmonary_embolism | `pe` | drop | physical examination abbreviation ambiguity |
| pulmonary_embolism | `p.e.` | drop | physical examination abbreviation ambiguity |
| pulmonary_embolism | `pes` | keep | plural pulmonary emboli shorthand |
| pulmonary_embolism | `pte` | keep | common thromboembolism abbreviation |
| pulmonary_embolism | `acute pulmonary embolism` | keep | acute diagnostic subtype |
| pulmonary_embolism | `acute pulmonary embolus` | keep | acute diagnostic subtype |
| pulmonary_embolism | `acute pulmonary thromboembolism` | keep | acute diagnostic subtype |
| pulmonary_embolism | `chronic pulmonary embolism` | keep | chronic diagnostic subtype |
| pulmonary_embolism | `chronic pulmonary embolus` | keep | chronic diagnostic subtype |
| pulmonary_embolism | `massive pulmonary embolism` | keep | severity-qualified pulmonary embolism |
| pulmonary_embolism | `massive pe` | keep | severity-qualified pulmonary embolism shorthand |
| pulmonary_embolism | `submassive pulmonary embolism` | keep | severity-qualified pulmonary embolism |
| pulmonary_embolism | `submassive pe` | keep | severity-qualified pulmonary embolism shorthand |
| pulmonary_embolism | `nonmassive pulmonary embolism` | keep | severity-qualified pulmonary embolism |
| pulmonary_embolism | `nonmassive pe` | keep | severity-qualified pulmonary embolism shorthand |
| pulmonary_embolism | `saddle pulmonary embolism` | keep | anatomic pulmonary embolism subtype |
| pulmonary_embolism | `saddle pe` | keep | anatomic pulmonary embolism shorthand |
| pulmonary_embolism | `bilateral pulmonary embolism` | keep | laterality-qualified pulmonary embolism |
| pulmonary_embolism | `bilateral pulmonary emboli` | keep | laterality-qualified pulmonary emboli |
| pulmonary_embolism | `unilateral pulmonary embolism` | keep | laterality-qualified pulmonary embolism |
| pulmonary_embolism | `segmental pulmonary embolism` | keep | anatomic pulmonary embolism subtype |
| pulmonary_embolism | `segmental pe` | keep | anatomic pulmonary embolism shorthand |
| pulmonary_embolism | `subsegmental pulmonary embolism` | keep | anatomic pulmonary embolism subtype |
| pulmonary_embolism | `subsegmental pe` | keep | anatomic pulmonary embolism shorthand |
| pulmonary_embolism | `lobar pulmonary embolism` | keep | anatomic pulmonary embolism subtype |
| pulmonary_embolism | `lobar pe` | keep | anatomic pulmonary embolism shorthand |
| pulmonary_embolism | `recurrent pulmonary embolism` | keep | recurrence-qualified pulmonary embolism |
| pulmonary_embolism | `recurrent pe` | keep | recurrence-qualified pulmonary embolism shorthand |
| pulmonary_embolism | `septic pulmonary embolism` | drop | distinct infectious embolic condition |
| pulmonary_embolism | `septic pulmonary emboli` | drop | distinct infectious embolic condition |
| pulmonary_embolism | `pulmonary tumor embolism` | drop | distinct neoplastic embolic condition |
| pulmonary_embolism | `pulmonary tumor emboli` | drop | distinct neoplastic embolic condition |
| rheumatoid_arthritis | `rheumatoid arthritis` | keep | standard diagnosis name |
| rheumatoid_arthritis | `ra` | drop | ambiguous with room air |
| rheumatoid_arthritis | `r.a.` | drop | ambiguous clinical abbreviation |
| rheumatoid_arthritis | `rheumatoid disease` | keep | synonym for rheumatoid arthritis |
| rheumatoid_arthritis | `atrophic arthritis` | keep | synonym for rheumatoid arthritis |
| rheumatoid_arthritis | `rheumatoid polyarthritis` | keep | rheumatoid arthritis synonym |
| rheumatoid_arthritis | `seropositive rheumatoid arthritis` | keep | serologic rheumatoid arthritis subtype |
| rheumatoid_arthritis | `seronegative rheumatoid arthritis` | keep | serologic rheumatoid arthritis subtype |
| rheumatoid_arthritis | `seropositive ra` | keep | abbreviated rheumatoid arthritis subtype |
| rheumatoid_arthritis | `seronegative ra` | keep | abbreviated rheumatoid arthritis subtype |
| rheumatoid_arthritis | `rheumatoid arthritis with rheumatoid factor` | keep | rheumatoid factor positive disease |
| rheumatoid_arthritis | `rheumatoid arthritis without rheumatoid factor` | keep | rheumatoid factor negative disease |
| rheumatoid_arthritis | `rheumatoid arthritis mutilans` | keep | destructive rheumatoid arthritis subtype |
| rheumatoid_arthritis | `rheumatoid arthritis, unspecified` | keep | unspecified rheumatoid arthritis diagnosis |
| systemic_lupus_erythematosus | `systemic lupus erythematosus` | keep | Full diagnosis name |
| systemic_lupus_erythematosus | `systemic lupus` | keep | Common shortened diagnosis name |
| systemic_lupus_erythematosus | `lupus erythematosus` | keep | Standard lupus diagnosis wording |
| systemic_lupus_erythematosus | `lupus` | keep | Common clinical shorthand |
| systemic_lupus_erythematosus | `sle` | keep | Standard diagnosis abbreviation |
| systemic_lupus_erythematosus | `s.l.e.` | keep | Punctuated abbreviation variant |
| systemic_lupus_erythematosus | `lupus erythematosus disseminatus` | keep | Historical systemic lupus synonym |
| systemic_lupus_erythematosus | `disseminated lupus erythematosus` | keep | Historical systemic lupus synonym |
| systemic_lupus_erythematosus | `acute disseminated lupus erythematosus` | keep | Historical systemic lupus variant |
| systemic_lupus_erythematosus | `juvenile systemic lupus erythematosus` | keep | Juvenile systemic lupus subtype |
| systemic_lupus_erythematosus | `juvenile sle` | keep | Juvenile SLE abbreviation |
| systemic_lupus_erythematosus | `childhood-onset systemic lupus erythematosus` | keep | Childhood systemic lupus subtype |
| systemic_lupus_erythematosus | `pediatric systemic lupus erythematosus` | keep | Pediatric systemic lupus subtype |
| systemic_lupus_erythematosus | `late-onset systemic lupus erythematosus` | keep | Late-onset systemic lupus subtype |
| systemic_lupus_erythematosus | `neuropsychiatric systemic lupus erythematosus` | keep | Neuropsychiatric systemic lupus manifestation |
| type_1_diabetes | `type 1 diabetes mellitus` | keep | exact diagnosis name |
| type_1_diabetes | `type 1 diabetes` | keep | common diagnosis wording |
| type_1_diabetes | `type 1 dm` | keep | standard clinical abbreviation |
| type_1_diabetes | `type i diabetes mellitus` | keep | roman numeral variant |
| type_1_diabetes | `type i diabetes` | keep | roman numeral variant |
| type_1_diabetes | `type i dm` | keep | roman numeral abbreviation |
| type_1_diabetes | `diabetes mellitus type 1` | keep | reordered diagnosis wording |
| type_1_diabetes | `diabetes type 1` | keep | reordered diagnosis wording |
| type_1_diabetes | `diabetes mellitus type i` | keep | reordered roman numeral variant |
| type_1_diabetes | `diabetes type i` | keep | reordered roman numeral variant |
| type_1_diabetes | `t1dm` | keep | standard type 1 abbreviation |
| type_1_diabetes | `t1d` | keep | common type 1 abbreviation |
| type_1_diabetes | `dm1` | keep | common diabetes type abbreviation |
| type_1_diabetes | `dmt1` | keep | abbreviated type 1 diabetes |
| type_1_diabetes | `insulin-dependent diabetes mellitus` | keep | historical type 1 synonym |
| type_1_diabetes | `insulin-dependent diabetes` | keep | historical type 1 synonym |
| type_1_diabetes | `insulin-dependent dm` | keep | historical type 1 abbreviation |
| type_1_diabetes | `insulin dependent diabetes mellitus` | keep | punctuation variant synonym |
| type_1_diabetes | `insulin dependent diabetes` | keep | punctuation variant synonym |
| type_1_diabetes | `insulin dependent dm` | keep | punctuation variant abbreviation |
| type_1_diabetes | `iddm` | keep | historical type 1 abbreviation |
| type_1_diabetes | `juvenile diabetes mellitus` | keep | historical type 1 synonym |
| type_1_diabetes | `juvenile diabetes` | keep | common type 1 synonym |
| type_1_diabetes | `juvenile-onset diabetes mellitus` | keep | historical type 1 synonym |
| type_1_diabetes | `juvenile-onset diabetes` | keep | historical type 1 synonym |
| type_1_diabetes | `autoimmune diabetes mellitus` | keep | autoimmune type 1 wording |
| type_1_diabetes | `autoimmune diabetes` | keep | autoimmune type 1 wording |
| type_1_diabetes | `type 1a diabetes` | keep | type 1 autoimmune subtype |
| type_1_diabetes | `type 1a diabetes mellitus` | keep | type 1 autoimmune subtype |
| type_1_diabetes | `type 1b diabetes` | keep | type 1 idiopathic subtype |
| type_1_diabetes | `type 1b diabetes mellitus` | keep | type 1 idiopathic subtype |
| type_1_diabetes | `brittle diabetes` | keep | unstable type 1 descriptor |
| type_1_diabetes | `brittle diabetes mellitus` | keep | unstable type 1 descriptor |
| type_2_diabetes | `type 2 diabetes mellitus` | keep | standard full diagnosis name |
| type_2_diabetes | `type 2 diabetes` | keep | common shortened diagnosis name |
| type_2_diabetes | `type 2 dm` | keep | standard clinical abbreviation |
| type_2_diabetes | `type ii diabetes mellitus` | keep | roman numeral diagnosis variant |
| type_2_diabetes | `type ii diabetes` | keep | common roman numeral shorthand |
| type_2_diabetes | `type ii dm` | keep | roman numeral clinical abbreviation |
| type_2_diabetes | `diabetes mellitus type 2` | keep | standard word order variant |
| type_2_diabetes | `diabetes mellitus type ii` | keep | roman numeral word order variant |
| type_2_diabetes | `diabetes type 2` | keep | common reordered diagnosis shorthand |
| type_2_diabetes | `diabetes type ii` | keep | roman numeral reordered shorthand |
| type_2_diabetes | `dm type 2` | keep | common abbreviated word order |
| type_2_diabetes | `dm type ii` | keep | roman numeral abbreviated word order |
| type_2_diabetes | `dm2` | keep | common type two abbreviation |
| type_2_diabetes | `dmt2` | keep | abbreviated diabetes mellitus type two |
| type_2_diabetes | `t2dm` | keep | standard clinical abbreviation |
| type_2_diabetes | `t2 dm` | keep | spaced abbreviation variant |
| type_2_diabetes | `t2-dm` | keep | hyphenated abbreviation variant |
| type_2_diabetes | `t2d` | keep | common type two diabetes shorthand |
| type_2_diabetes | `non-insulin-dependent diabetes mellitus` | keep | legacy name for type two |
| type_2_diabetes | `non-insulin-dependent diabetes` | keep | legacy shortened diagnosis name |
| type_2_diabetes | `non-insulin-dependent dm` | keep | legacy abbreviated diagnosis name |
| type_2_diabetes | `niddm` | keep | standard legacy clinical abbreviation |
| type_2_diabetes | `adult-onset diabetes mellitus` | keep | legacy type two diagnosis term |
| type_2_diabetes | `adult-onset diabetes` | keep | common legacy diagnosis shorthand |
| type_2_diabetes | `adult-onset dm` | keep | legacy abbreviated diagnosis term |
