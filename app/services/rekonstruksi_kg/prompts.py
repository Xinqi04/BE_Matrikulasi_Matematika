STRUCTURE_RESOLVER_PROMPT = """Kamu adalah analis struktur dokumen.
Diberikan kandidat struktur dari dokumen PDF, selesaikan struktur hirarki dokumen (BAB dan SUBBAB).

Input berupa daftar teks yang terdeteksi sebagai kandidat heading beserta level heuristiknya.
Tugas:
1. Buat struktur canonical (BAB dan SUBBAB) yang rapi.
2. JANGAN memaksakan setiap BAB memiliki SUBBAB jika memang tidak ada.
3. Buat ringkasan (summary) singkat untuk setiap unit (2-4 kalimat). Summary harus menjelaskan konteks dan cakupan pembahasan.
3. Subbab bisa memiliki nama A B C, dst. jika tidak ada nama yang jelas. tidak harus 1.1 1.2 dst

Output dalam format JSON dengan skema berikut:
{
    "units": [
        {
            "id": "unit_id",
            "level": "BAB",
            "title": "Judul BAB",
            "parent_id": null,
            "start_page": 1,
            "end_page": 10,
            "summary": "...",
            "has_children": true
        }
    ]
}
Pastikan output adalah valid JSON.
"""

EXTRACTION_PROMPT = """Kamu adalah extractor topik pembelajaran dari materi akademik apa pun bidangnya — matematika, sains, ilmu sosial, bahasa, teknik, ekonomi, dll. Aturan dan contoh di bawah berlaku umum untuk semua bidang; contoh bertema matematika hanya ilustrasi.

Tugas:
Identifikasi topik/konsep pembelajaran yang dibahas dalam unit, dengan tingkat detail yang wajar. Usahakan minimal 2 konsep per unit selama raw text memang punya cukup isi untuk itu — pecah topik besar jadi beberapa sub-topik yang lebih spesifik daripada meringkasnya jadi 1 konsep tunggal yang generik. 1 konsep saja hanya dipakai kalau raw text benar-benar pendek/sempit dan cuma membahas satu ide saja.

Dalam tugas ini:
- konsep = sub-topik pembelajaran yang dijelaskan di dalam raw text (definisi, aturan, sifat, prosedur, klasifikasi, atau prinsip).
- konsep bukan simbol, angka, atau langkah pengerjaan satu soal tertentu.
- kalau unit membahas beberapa sub-topik yang berbeda, masing-masing sebaiknya jadi konsep sendiri dengan nama yang mencerminkan sub-topik tersebut, bukan diringkas semua jadi satu nama umum yang sama dengan judul unit.

Tujuan utama:
Menghasilkan daftar konsep sebagai representasi topik pembelajaran unit, dipakai sebagai fitur untuk Content-Based Filtering. Deskripsi tiap konsep sebaiknya menyebut detail dari raw text (definisi/aturan/karakteristiknya), bukan cuma menyalin ulang title/summary unit.

Gunakan:
- raw text sebagai sumber informasi utama
- title, summary, dan parent sebagai konteks tambahan untuk memahami cakupan unit

Panduan gabung vs pisah (tidak perlu terlalu kaku, gunakan penilaian wajar):
- Gabungkan istilah-istilah yang sebenarnya sinonim atau sama-sama contoh/turunan dari satu aturan yang sama (mis. "Kuadrat Jumlah", "Kuadrat Selisih", "Selisih Dua Kuadrat" → "Identitas Aljabar").
- Pisahkan sub-topik yang masing-masing dijelaskan dengan fokus berbeda (mis. "notasi eksponen" dan "sifat-sifat operasi eksponen" adalah dua hal berbeda meskipun sama-sama di bawah judul "Eksponen").
- Kalau raw text ternyata cuma membahas satu ide saja tanpa sub-topik lain sama sekali, baru satu konsep saja boleh cukup. Selain itu, coba cari minimal 2 sudut/sub-topik berbeda (misalnya: definisi/notasi vs aturan/sifatnya, atau klasifikasi vs penerapannya) daripada langsung menyimpulkan jadi satu konsep besar.

ATURAN EKSTRAKSI:

1. Ekstrak topik yang memang dibahas dan didukung oleh raw text (bukan mengarang topik yang tidak ada).
2. Topik yang diekstrak sebaiknya punya penjelasan yang cukup jelas (definisi/aturan/karakteristik), bukan sekadar disebut satu kali tanpa konteks apapun.
3. Jangan jadikan konsep terpisah untuk: contoh soal, angka/simbol individual, atau langkah pengerjaan spesifik.
4. Nama konsep: ringkas, spesifik terhadap apa yang dibahas, dan menggunakan istilah akademik yang lazim di bidangnya.
5. Jangan mengulang konsep yang sama dengan variasi nama — kalau ada, gabungkan jadi satu dengan nama yang paling representatif.
6. Hindari nama konsep yang terlalu generik (nama bidang ilmu itu sendiri, atau kategori besar seperti "Operasi", "Aturan Dasar") kecuali memang itulah topik utama yang dibahas secara eksplisit dan spesifik di unit.
7. Judul unit boleh dipakai sebagai nama salah satu konsep bila memang cocok, tapi jangan jadikan SATU-SATUNYA konsep dengan cara memaksa semua sub-topik berbeda melebur ke dalamnya — kalau ada sub-topik lain yang jelas dibahas terpisah, buat juga konsep untuk itu supaya hasilnya minimal 2 konsep.
8. Jika unit tidak punya topik pembelajaran yang cukup jelas, kembalikan array konsep kosong.
9. Output harus JSON valid tanpa teks tambahan di luar JSON.

FORMAT OUTPUT:

{{
    "unit_id": "{unit_id}",
    "konsep": [
        {{
            "nama": "...",
            "deskripsi": "Deskripsi singkat mengenai topik pembelajaran yang dibahas."
        }}
    ]
}}

DATA UNIT:

Title:
{title}

Summary:
{summary}

Parent:
{parent}

Raw Text:
{raw_text}
"""


CONSOLIDATION_PROMPT = """Kamu adalah konsolidator konsep pembelajaran hasil ekstraksi dari seluruh unit (BAB/SUBBAB) sebuah dokumen.

Setiap konsep pada input berasal dari sebuah unit_id tertentu (unit tempat konsep tersebut diekstrak).
Kamu juga diberikan daftar seluruh unit beserta judulnya sebagai konteks struktur dokumen.

Yang perlu kamu benahi (secukupnya, jangan berlebihan):

1. Duplikat/variasi penulisan dari konsep yang BENAR-BENAR SAMA:
   Kalau ada dua entri yang jelas-jelas membahas ide yang identik hanya beda penulisan (mis. "Eksponen" vs "Bilangan Berpangkat" yang deskripsinya sama-sama menjelaskan hal yang sama persis), gabungkan jadi satu nama yang paling standar.

2. Konsep yang salah tempat:
   Kadang sebuah istilah cuma disinggung sekilas di suatu unit sebagai referensi/prasyarat, padahal ada unit lain yang memang membahasnya secara khusus (contoh: "Radikal" cuma disebut selintas di unit "Eksponen", padahal ada unit tersendiri berjudul "Radikal" yang menjelaskannya secara lengkap). Untuk kasus seperti ini, pindahkan konsep tersebut ke unit yang paling tepat membahasnya, dan hapus versi yang cuma disinggung sekilas.

Yang TIDAK perlu diubah — biarkan apa adanya:
- Kalau dua unit berbeda memang sama-sama membahas suatu konsep secara substantif dengan fokus/cakupan yang berbeda (bukan sekadar disinggung sekilas), itu BUKAN duplikat salah tempat — biarkan masing-masing tetap di unit_id asalnya.
- Konsep dengan nama mirip tapi topiknya sebenarnya berbeda jangan digabung.
- Kalau ragu apakah suatu konsep perlu dipindah/digabung atau tidak, lebih baik biarkan di unit_id asalnya daripada memindah/menggabung secara asal.

Cara memilih unit_id ketika memang perlu memindahkan konsep:
- Utamakan unit yang judulnya (title) memang tentang konsep tersebut.
- Kalau tidak ada, pilih unit dengan deskripsi paling lengkap/substantif untuk konsep itu.

RULES TAMBAHAN:
- Gunakan deskripsi yang paling jelas dan paling lengkap di antara variasi konsep yang digabung.
- Output harus JSON valid tanpa teks tambahan di luar JSON.

FORMAT OUTPUT:
{
    "konsep": [
        {
            "unit_id": "unit_id_kanonik",
            "nama": "...",
            "deskripsi": "..."
        }
    ]
}

Daftar unit (unit_id + title):
{units_json}

Daftar konsep hasil ekstraksi (sebelum konsolidasi):
{concepts_json}
"""
