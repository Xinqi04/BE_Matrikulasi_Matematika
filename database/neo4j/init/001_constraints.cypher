// Neo4j hanya menjadi source of truth untuk knowledge graph dan proyeksi referensi soal.
CREATE CONSTRAINT modul_id IF NOT EXISTS FOR (n:Modul) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT bab_id IF NOT EXISTS FOR (n:Bab) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT subbab_id IF NOT EXISTS FOR (n:SubBab) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT konsep_nama IF NOT EXISTS FOR (n:Konsep) REQUIRE n.nama IS UNIQUE;
CREATE CONSTRAINT materi_id IF NOT EXISTS FOR (n:Materi) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT soal_ref_id IF NOT EXISTS FOR (n:SoalRef) REQUIRE n.id IS UNIQUE;

CREATE INDEX bab_nomor IF NOT EXISTS FOR (n:Bab) ON (n.nomor);
CREATE INDEX subbab_nomor IF NOT EXISTS FOR (n:SubBab) ON (n.nomor);
CREATE INDEX materi_tipe IF NOT EXISTS FOR (n:Materi) ON (n.tipe);
