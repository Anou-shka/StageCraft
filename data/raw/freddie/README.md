# Put the Freddie Mac sample files here

1. Register (free) and sign in at the Freddie Mac Single-Family Loan-Level Dataset page:
   https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset
2. Under **Sample dataset**, download one zip per origination year:

   `sample_2005.zip`, `sample_2006.zip`, ..., `sample_2019.zip` (15 files)

   Each contains `sample_orig_YYYY.txt` (origination) and `sample_perf_YYYY.txt` (`sample_svcg_YYYY.txt` in older releases)
   (monthly performance through the latest cut-off, so post-2019 validation data is included).
3. Drop the zips into this folder unchanged (no need to unzip) and run
   `python -m stagecraft.pipeline`.

These files are licensed by Freddie Mac and are git-ignored: never commit them.
When this folder is empty the pipeline falls back to the synthetic sample in `data/sample/freddie/`.
