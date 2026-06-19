# PII CLEANUP REPORT — SECURITY_LOCK V1 / ART.1

**Data:** 2026-06-19 04:13:35 UTC
**Operação:** `git rm --cached` + `.gitignore`
**Princípio:** Arquivos REMOVIDOS do versionamento, PRESERVADOS localmente.

## Resumo
- **Total de arquivos removidos do git:** 47 (37 uploads + 10 holerites)
- **Total de arquivos preservados em disco:** 47 (intactos)
- **Categorias:** uploads de cliente (áudios WA, fotos pré-atendimento, transcripts PDF, parcerias) + planilha de contatos + holerites PDF assinados/draft

## .gitignore (regras adicionadas)
```
backend/uploads/
backend/data_imports/*.xlsx
backend/data_imports/*.csv
backend/data_imports/*.ofx
data/holerites/
```

## Arquivos removidos do git (preservados localmente) com SHA256

| Arquivo | SHA256 |
|---------|--------|
| `backend/data_imports/full_contatos.xlsx` | `25448faf54ded6e2d565fa90b31e9b2d...` |
| `backend/uploads/parcerias/pa-dc50a93b30f7-fe2f05287b0e.png` | `6b7fa434f92a8b80aab02d9bf1a12e49...` |
| `backend/uploads/pre_attendance/co-demo_3beddfcd02884b.png` | `cdb8644595354e6f8d0160f42e70c72d...` |
| `backend/uploads/pre_attendance/co-demo_43c1cff52c154e.png` | `cdb8644595354e6f8d0160f42e70c72d...` |
| `backend/uploads/pre_attendance/co-demo_83196409feac41.png` | `cdb8644595354e6f8d0160f42e70c72d...` |
| `backend/uploads/pre_attendance/co-demo_ae2e5f43592b46.png` | `cdb8644595354e6f8d0160f42e70c72d...` |
| `backend/uploads/wa_audio/wam-117c021386.ogg` | `6458be2c875b349a933ab55945234762...` |
| `backend/uploads/wa_audio/wam-1784f0c8fa.ogg` | `66bd8373e73400133422c292768aa6ee...` |
| `backend/uploads/wa_audio/wam-1c3d64d9a3.ogg` | `10aa34081994f70fdeaf3da19a95cc85...` |
| `backend/uploads/wa_audio/wam-23dc0b401a.ogg` | `98db00e7f254fde517a54ba01ad11bb9...` |
| `backend/uploads/wa_audio/wam-24663abab0.ogg` | `8705188ff3d84ad01637cab152b4dc04...` |
| `backend/uploads/wa_audio/wam-2c01e11cfc.ogg` | `c23a5ba8cbd098d40df47461c01453ec...` |
| `backend/uploads/wa_audio/wam-37b9e0ac7d.ogg` | `1745d33194057a0041b4016a53476328...` |
| `backend/uploads/wa_audio/wam-49af1a9479.ogg` | `a35efb79bb20ee2f0a469920b334258f...` |
| `backend/uploads/wa_audio/wam-4f93b67367.ogg` | `bca22538789ea9fd4e97a5309061272a...` |
| `backend/uploads/wa_audio/wam-5938b91bbc.ogg` | `4c92e55ad9d4e2ae4abe5d76aea8f556...` |
| `backend/uploads/wa_audio/wam-6ac99324cf.ogg` | `ce476875aefef863f35f751b4cf34dd7...` |
| `backend/uploads/wa_audio/wam-6b01d7e659.webm` | `a87d1477a574f806d9eca4431abf77bc...` |
| `backend/uploads/wa_audio/wam-6bb26b5d7d.ogg` | `002f2b7fc8315f1470cc9fcaaba25102...` |
| `backend/uploads/wa_audio/wam-6f07e71868.ogg` | `16de50fe7395d53e98b4c1ad52130cb4...` |
| `backend/uploads/wa_audio/wam-7bb7c73b45.webm` | `bca22538789ea9fd4e97a5309061272a...` |
| `backend/uploads/wa_audio/wam-97cb278fd2.ogg` | `c13d3f8e561e69d274352a1cac749141...` |
| `backend/uploads/wa_audio/wam-b1c3ccdf5f.ogg` | `bca22538789ea9fd4e97a5309061272a...` |
| `backend/uploads/wa_audio/wam-b5d00bd299.ogg` | `a35efb79bb20ee2f0a469920b334258f...` |
| `backend/uploads/wa_audio/wam-b7a2dea217.ogg` | `bca22538789ea9fd4e97a5309061272a...` |
| `backend/uploads/wa_audio/wam-b8dc32b66e.ogg` | `f8b0458e730440d9e7231e066505a590...` |
| `backend/uploads/wa_audio/wam-c6554ce9a6.webm` | `6fe851c103072ce3f92205c34d03f881...` |
| `backend/uploads/wa_audio/wam-cc35d5a4b4.ogg` | `bca22538789ea9fd4e97a5309061272a...` |
| `backend/uploads/wa_audio/wam-cee48ff8d5.ogg` | `23ca7373f2f878bf67ae5a8cb4039dad...` |
| `backend/uploads/wa_audio/wam-d688b5e933.ogg` | `2d595e51ee44bc92d0381fc4a21165bf...` |
| `backend/uploads/wa_audio/wam-ed63a584e7.ogg` | `41c994d6afe801afd732c82a347af821...` |
| `backend/uploads/wa_quickimages/wqi-c22db236e3.jpeg` | `0c6b4ec7507a9f74ae866125a3cf46e3...` |
| `backend/uploads/wa_transcripts/watp-2a283bd652.pdf` | `aadf40a03f101003fbc176e975623cef...` |
| `backend/uploads/wa_transcripts/watp-2d74b348e2.pdf` | `08f9e8816d8afcae4e918080029cc4ea...` |
| `backend/uploads/wa_transcripts/watp-3775b0438d.pdf` | `59a8343e92efc7bc9d3bee02f600d695...` |
| `backend/uploads/wa_transcripts/watp-5c8be6af1d.pdf` | `268b75fa189973767b9a906e782a3778...` |
| `backend/uploads/wa_transcripts/watp-de633500d9.pdf` | `d100dc64df629f286f28ba872185bc85...` |

## Verificação
```bash
$ git ls-files backend/uploads/ backend/data_imports/ | wc -l
0

$ ls backend/uploads/ | wc -l
8 (diretórios preservados)
```

## Conformidade
- ✅ ART.1 — PII não-versionado
- ✅ Histórico do git contém os blobs ainda (limpeza via `git filter-repo` fica para próxima fase)
- ✅ Disco mantém todos os arquivos (uploads ativos do app)
