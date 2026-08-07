"""Seed soal untuk BAB 1 (Bilangan Real) & BAB 2 (Eksponen) modul Matematika Dasar, lengkap
dengan mapping ke Konsep yang sudah ada di Neo4j (hasil ekstraksi PDF modul). Jalankan dari
folder `backend/`:

    python scripts/seed_soal_matematika_dasar.py

Idempoten per BAB: kalau BAB itu udah punya `:Soal`, bab tsb dilewati (gak dobel insert).
`tingkat_kesulitan` sengaja dikosongkan (belum dipakai). Notasi pecahan ditulis pakai
slash biasa ("2/3", bukan simbol unicode "⅔" atau LaTeX) karena `teks_soal` di frontend
dirender sebagai teks polos (lihat BabSoal.jsx) -- slash biasa yang paling konsisten
tampil benar di semua device/font tanpa perlu math renderer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.neo4j_client import neo4j_session  # noqa: E402
from app.services import soal_pipeline  # noqa: E402

MODUL_ID = "modul_matrikulasi_matematika_dasar"

SOAL_BAB1 = [
    dict(
        teks_soal="Dalam sebuah pertandingan sepak bola, papan skor mencatat angka-angka "
                  "berikut sepanjang pertandingan: -1 (gol dianulir), 0, 2, dan 5. Dari "
                  "angka-angka tersebut, manakah yang merupakan bilangan asli?",
        tipe="isian_singkat",
        jawaban_referensi="2 dan 5 (bilangan asli dimulai dari 1, 2, 3, ...; 0 termasuk "
                           "bilangan cacah tapi bukan asli; -1 bukan keduanya karena negatif).",
        konsep=["sistem bilangan (natural, cacah, dan bulat)"],
    ),
    dict(
        teks_soal="Kelompokkan bilangan berikut ke dalam rasional atau irasional: 0.75, "
                  "akar 2, 5/3, pi, akar 16.",
        tipe="isian_singkat",
        jawaban_referensi="Rasional: 0.75, 5/3, akar 16 (=4). Irasional: akar 2, pi.",
        konsep=["bilangan rasional", "bilangan irasional", "sistem bilangan real",
                "himpunan bilangan khusus"],
    ),
    dict(
        teks_soal="Sebuah resep kue membutuhkan 2/3 cangkir tepung. Karena Rani cuma mau "
                  "membuat setengah resep, berapa cangkir tepung yang dia butuhkan?",
        tipe="isian_singkat",
        jawaban_referensi="(2/3) x (1/2) = 2/6 = 1/3 cangkir.",
        konsep=["operasi aritmatika bilangan rasional"],
    ),
    dict(
        teks_soal="Diketahui himpunan A = {x | x adalah bilangan genap, 1 <= x <= 10}. "
                  "Tuliskan himpunan A dalam bentuk pendaftaran (roster method).",
        tipe="isian_singkat",
        jawaban_referensi="A = {2, 4, 6, 8, 10}.",
        konsep=["definisi dan elemen himpunan", "representasi himpunan"],
    ),
    dict(
        teks_soal="Diketahui P = {1, 2, 3, 4, 5} dan Q = {3, 4, 5, 6, 7}. Tentukan P irisan Q "
                  "dan P gabungan Q, lalu jelaskan perbedaan makna dari kedua operasi tersebut.",
        tipe="esai",
        jawaban_referensi="P irisan Q = {3,4,5} (anggota yang ada di kedua himpunan). "
                           "P gabungan Q = {1,2,3,4,5,6,7} (semua anggota dari kedua himpunan "
                           "tanpa duplikat).",
        konsep=["operasi himpunan"],
    ),
    dict(
        teks_soal="Sebuah wahana roller coaster hanya boleh dinaiki pengunjung dengan tinggi "
                  "badan lebih dari 120 cm dan paling tinggi 190 cm (batas 190 cm masih boleh, "
                  "batas 120 cm belum boleh). Tuliskan syarat tinggi badan tersebut dalam "
                  "notasi interval.",
        tipe="isian_singkat",
        jawaban_referensi="(120, 190] -- 120 cm tidak termasuk (interval terbuka di kiri), "
                           "190 cm termasuk (interval tertutup di kanan).",
        konsep=["interval bilangan real", "jenis-jenis interval bilangan real"],
    ),
    dict(
        teks_soal="Tuliskan notasi interval untuk himpunan semua bilangan real yang lebih "
                  "besar dari -2 (tanpa batas atas).",
        tipe="isian_singkat",
        jawaban_referensi="(-2, tak hingga).",
        konsep=["interval tak terhingga"],
    ),
    dict(
        teks_soal="Tentukan nilai dari |-7| + |3| - |-2|.",
        tipe="isian_singkat",
        jawaban_referensi="7 + 3 - 2 = 8.",
        konsep=["nilai mutlak"],
    ),
    dict(
        teks_soal="Titik A menunjukkan posisi rumah Rani di angka -4 pada garis bilangan "
                  "(dalam km dari pusat kota), sedangkan sekolahnya berada di titik 9. Berapa "
                  "jarak yang harus ditempuh Rani dari rumah ke sekolah?",
        tipe="isian_singkat",
        jawaban_referensi="|9 - (-4)| = |13| = 13 km.",
        konsep=["jarak antara dua titik pada garis bilangan"],
    ),
]

SOAL_BAB2 = [
    dict(
        teks_soal="Tulis 5 x 5 x 5 x 5 dalam bentuk pangkat (eksponen), lalu hitung nilainya.",
        tipe="isian_singkat",
        jawaban_referensi="5^4 = 625.",
        konsep=["definisi eksponen"],
    ),
    dict(
        teks_soal="Sederhanakan bentuk berikut menggunakan sifat eksponen: (2^3 x 2^5) / 2^4.",
        tipe="isian_singkat",
        jawaban_referensi="2^(3+5-4) = 2^4 = 16.",
        konsep=["sifat operasi eksponen"],
    ),
    dict(
        teks_soal="Ukuran sebuah bakteri kira-kira 2^-3 mm. Ubah ukuran tersebut ke bentuk "
                  "pecahan biasa, lalu tentukan nilainya dalam mm.",
        tipe="isian_singkat",
        jawaban_referensi="2^-3 = 1/2^3 = 1/8 mm = 0.125 mm.",
        konsep=["eksponen negatif"],
    ),
    dict(
        teks_soal="Tentukan nilai dari akar pangkat tiga dari -27.",
        tipe="isian_singkat",
        jawaban_referensi="-3, karena (-3)^3 = -27.",
        konsep=["definisi akar ke-n"],
    ),
    dict(
        teks_soal="Sederhanakan bentuk akar berikut: akar 72.",
        tipe="isian_singkat",
        jawaban_referensi="akar 72 = akar(36 x 2) = 6 akar 2.",
        konsep=["penyederhanaan bentuk akar"],
    ),
    dict(
        teks_soal="Dua taman berbentuk persegi punya luas 8 m^2 dan 2 m^2. Panjang sisi tiap "
                  "taman dinyatakan dalam bentuk akar. Tunjukkan bahwa hasil kali sisi kedua "
                  "taman (akar 8 x akar 2) sama dengan sisi taman ketiga yang luasnya 16 m^2.",
        tipe="esai",
        jawaban_referensi="akar 8 x akar 2 = akar(8x2) = akar 16 = 4, dan sisi taman berluas "
                           "16 m^2 juga akar 16 = 4, jadi terbukti sama.",
        konsep=["sifat-sifat operasi akar ke-n"],
    ),
    dict(
        teks_soal="Ubah bentuk akar pangkat 5 dari x^10 ke eksponen rasional (pangkat "
                  "pecahan), lalu sederhanakan.",
        tipe="isian_singkat",
        jawaban_referensi="akar-5(x^10) = x^(10/5) = x^2.",
        konsep=["eksponen rasional"],
    ),
    dict(
        teks_soal="Rasionalkan penyebut dari pecahan 5/akar3, lalu jelaskan langkah-langkahnya.",
        tipe="esai",
        jawaban_referensi="5/akar3 x akar3/akar3 = 5 akar3 / 3. Kalikan pembilang & penyebut "
                           "dengan akar3 supaya penyebut jadi bilangan rasional (akar dikali "
                           "dirinya sendiri jadi hilang akarnya).",
        konsep=["rasionalisasi penyebut"],
    ),
]

DAFTAR_BAB = [
    (f"{MODUL_ID}_bab1", SOAL_BAB1),
    (f"{MODUL_ID}_bab2", SOAL_BAB2),
]


def main() -> None:
    with neo4j_session() as session:
        def _cari_dosen_id(tx):
            r = tx.run("MATCH (u:User {role: 'dosen'}) RETURN u.id AS id LIMIT 1")
            rec = r.single()
            return rec["id"] if rec else "seed_script"

        dibuat_oleh = session.execute_read(_cari_dosen_id)

        for bab_id, daftar_soal in DAFTAR_BAB:
            def _sudah_ada(tx, bab_id=bab_id):
                r = tx.run("MATCH (:Bab {id: $bab_id})-[:HAS_SOAL]->(s:Soal) RETURN count(s) AS n",
                           bab_id=bab_id)
                return r.single()["n"]

            if session.execute_read(_sudah_ada) > 0:
                print(f"{bab_id}: sudah ada soal -- dilewati.")
                continue

            for data in daftar_soal:
                soal = soal_pipeline.buat_soal(
                    session, bab_id=bab_id, teks_soal=data["teks_soal"], tipe=data["tipe"],
                    konsep_list=data["konsep"], dibuat_oleh=dibuat_oleh,
                    jawaban_referensi=data["jawaban_referensi"], tingkat_kesulitan=None,
                )
                print(f"{bab_id}: soal dibuat -- {soal['id']} ({len(soal['konsep'])} konsep)")


if __name__ == "__main__":
    main()
