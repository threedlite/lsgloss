# The dictionary, treebanks and corpus are cloned into data-sources/ -- either
# inside this checkout (the README's setup commands) or beside it, which is how
# the working tree that produced the shipped package is laid out. Take
# whichever exists; override on the command line for anything else.
DATA ?= $(firstword $(wildcard data-sources ../data-sources) data-sources)
XML ?= $(DATA)/lexica/CTS_XML_TEI/perseus/pdllex/lat/ls/lat.ls.perseus-eng2.xml
JOBS ?= 4
FREQ ?= out/latin_freq.tsv
TREEBANK ?= $(DATA)/treebank_data/v2.0/Latin
CORPUS ?= $(DATA)/canonical-latinLit
# the raw model replies every gloss was cleaned from; lives beside the TSV that
# `make run` wrote, which for the shipped data is the working tree above
CKPT ?= $(firstword $(wildcard out/ckpt.jsonl ../out/ckpt.jsonl) out/ckpt.jsonl)

run:            ## gloss the whole dictionary (resumable)
	python3 lsgloss.py --xml $(XML) -j $(JOBS) --ckpt $(CKPT)

rebuild:        ## rebuild the TSV from the checkpoint with the current rules (no model)
	python3 lsgloss.py --xml $(XML) --ckpt $(CKPT) --offline --carry out/ls_glosses.tsv
	python3 refinalise.py --tsv out/ls_glosses.tsv --xml $(XML)   # the carried rows get the same clean+enforce

test:           ## unit + integration suite (no model, no network, ~25s)
	python3 -m unittest discover -s tests -t . -v

regress:        ## diff every model-free function against the committed baseline
	python3 regress.py --xml $(XML) --ckpt $(CKPT)

baseline:       ## rewrite the regression baseline AFTER reviewing the diff
	python3 regress.py --xml $(XML) --ckpt $(CKPT) --accept

check:          ## everything that guards a change: suite + corpus diff
	$(MAKE) test
	$(MAKE) regress

smoke:          ## 500-entry end-to-end run against a live model
	python3 lsgloss.py --xml $(XML) -n 500 -j $(JOBS) --out out/test.tsv --ckpt out/test.jsonl

freq:           ## build the corpus frequency list (no model needed)
	python3 corpusfreq.py --corpus $(CORPUS) --out $(FREQ)

score:          ## judge every gloss
	python3 score.py --xml $(XML) -n 0 -j $(JOBS) --out out/scores_full.tsv

lemmas:         ## model-supplied lemmas for irregular forms
	python3 lemmatize.py --xml $(XML) --freq $(FREQ) -j $(JOBS) --out out/lemma_map.tsv

lemmas-offline: ## rebuild the lemma map from its checkpoint with the current rules (no model)
	python3 lemmatize.py --xml $(XML) --freq $(FREQ) --out out/lemma_map.tsv --offline \
		--ckpt $(firstword $(wildcard out/lemma_ckpt.jsonl ../out/lemma_ckpt.jsonl) out/lemma_ckpt.jsonl)

freqfix:        ## repair the most frequent entries first (needs a corpus frequency list)
	python3 freqfix.py --xml $(XML) --freq $(FREQ) --screen --min-score 3 --top 1200

package:        ## build the importable Classics Viewer ZIP
	python3 package.py --xml $(XML) --tsv out/ls_glosses.tsv --scores out/scores_full.tsv \
		--lemma-map out/lemma_map.tsv --treebank $(TREEBANK) --freq $(FREQ)

check-size:     ## fail if anything committable is near GitHub's file-size limit
	sh check_size.sh

freqqa:         ## coverage and defects weighted by corpus frequency
	python3 freqqa.py --tsv out/ls_glosses.tsv --freq $(FREQ) --xml $(XML)

morphacc:       ## morph_info accuracy against held-out treebank tags
	python3 package.py --xml $(XML) --tsv out/ls_glosses.tsv --scores out/scores_full.tsv \
		--lemma-map out/lemma_map.tsv --freq $(FREQ) --out out/heldout.zip
	python3 eval/morphacc.py out/heldout.zip $(TREEBANK)

eval:           ## score against the gold set
	python3 eval/run_eval.py --xml $(XML)

qa:             ## QA summary of the output
	python3 qa_report.py out/ls_glosses.tsv

.PHONY: run rebuild test regress baseline check smoke eval qa freq score lemmas lemmas-offline freqfix package freqqa check-size morphacc
