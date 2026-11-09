# Public Workload Data Traces

This repository uses public workload accounting traces from the Parallel Workloads Archive maintained by the Hebrew University of Jerusalem.

---

## 1. CEA-Curie Trace (CEA-Curie-2011-2.swf.gz)

- **Source URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/index.html`
- **Download URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/CEA-Curie-2011-2.swf.gz`
- **System**: Curie supercomputer operated by CEA (Commissariat à l'énergie atomique et aux énergies alternatives) for GENCI.
- **Architecture**: Bullx B510 cluster comprising 5,040 nodes and 93,312 compute cores.
- **Trace Duration**: 20 months (February 2011 to October 2012).
- **Header Pragmas**:
  - `UnixStartTime`: `1303893309`
  - `MaxProcs`: `93312`
  - `MaxNodes`: `5040`
  - `Note`: `CEA Curie supercomputer log`
- **Usage Terms**: Traces from the Parallel Workloads Archive are freely accessible for academic, scientific, and comparative scheduling research. Publications and derivatives should cite the archive and the original trace contributors.

---

## 2. SDSC SP2 Trace (SDSC-SP2-1998-4.2-cln.swf.gz)

- **Source URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/index.html`
- **Download URL**: `https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/SDSC-SP2-1998-4.2-cln.swf.gz`
- **System**: IBM SP2 supercomputer at the San Diego Supercomputer Center (SDSC).
- **Architecture**: 128 compute nodes with dedicated memory per processor.
- **Trace Duration**: 24 months (April 1998 to April 2000).
- **Header Pragmas**:
  - `UnixStartTime`: `893744030`
  - `MaxProcs`: `128`
  - `MaxNodes`: `128`
  - `Note`: `SDSC SP2 trace`
- **Usage Terms**: Freely accessible for research and evaluation purposes with attribution to the San Diego Supercomputer Center and the Parallel Workloads Archive.

---

## 3. Data Storage Rules

- Large downloaded files (`*.swf`, `*.swf.gz`, `*.parquet`) are excluded by `data/.gitignore`.
- Tests must never access external networks during execution.
- Committed synthetic fixtures in `tests/fixtures/` represent miniature traces used exclusively for unit and integration testing.
