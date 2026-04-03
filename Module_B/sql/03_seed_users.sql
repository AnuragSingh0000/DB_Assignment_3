USE olympia_auth;

INSERT INTO users (username, password_hash, role, member_id) VALUES
('vikram_admin',     '$2b$12$bhbPO9.SFG87rECtLCCV3uXeb91Ujdmsv/rdcinl0qpUENlbThmyK', 'Admin',  18),
('raj_coach',        '$2b$12$3Jyg.YKaTiiabyKkBTeVWOwXPnDok6qYVfNX5HJ2szbPkJXOILL6y', 'Coach',  13),
('aarav_player',     '$2b$12$GLQVY5h7FI6.fskXwXxT9.w8AyoxhDXnAMiR5uyEx/WTBie6WxGVi', 'Player', 1),
-- remaining seed members (password: password123)
('meera_player',     '$2b$12$4pNxD8FOqQ2j6noZbw..VOP9.kQL5bCf3yw33BzoPM4wQty8vScSq', 'Player', 2),
('rohan_player',     '$2b$12$QoCLUiBDGl8IscwKxwsBK.5FF1qIFADRVJo/Rg/lmGc9e/1dkpFBq', 'Player', 3),
('priya_player',     '$2b$12$.zr2QH7CLWuAOECPRITWRedqvQHxC2LVvzjq21gjRDiFrW534cHSy', 'Player', 4),
('arjun_player',     '$2b$12$4qJbbg/4G/Vhz6A6WGsscueGbKIHI0Scs/2tv.SbegNa8qIlIEP/.', 'Player', 5),
('kavya_player',     '$2b$12$UZHalN.MSlMJQVKQI7Ixd.fVpiJZgbHLLxM9s5WPJlWc66DsQTZo2', 'Player', 6),
('vikash_player',    '$2b$12$/tXmfPwNHIgq5cD2q/Li9eOneJZZCVBSHUTH7fLlCcOU1QyMUvywC', 'Player', 7),
('ananya_player',    '$2b$12$DJ53pIA.UjJBW4yJ216lWerFslLpet2Vc9R2w22K8a62T5XgVlXf2', 'Player', 8),
('siddharth_player', '$2b$12$qtnBR.ovJ6pvWMjT6u0A5udn/nRAEC/oHNTGASj0T3EG5WSUSFUDO', 'Player', 9),
('riya_player',      '$2b$12$.mXWW3NzzSNf6DmkuHrlfeLYWvzBHSXoVc/1o.4ZipicKuh6pr9Xi', 'Player', 10),
('harsh_player',     '$2b$12$iUHJsn34Qy.PKbivoiO6tuHOt4ML7RK70GNnJiZWPdRqiyQ86R/ve', 'Player', 11),
('diya_player',      '$2b$12$WVXCCl4KpKIaLq.mK6ODV.m9URJO7Bt4rmAf8YZEAgyVBo1W8NlpW', 'Player', 12),
('sunita_coach',     '$2b$12$rSGOLdbvcrQyclKInZDcbO9xaeX8uZNqXN3T/goKJ7Hkwe6qFP/26', 'Coach',  14),
('deepak_coach',     '$2b$12$eJCEvTdg0tqAfISQQvbyL.3MKqjTVR/milPrfUoNhXwAuLR6NP.1C', 'Coach',  15),
('pooja_coach',      '$2b$12$OzRs2KW6QkyxNjBmg9cpHOx1lI6nCBkt.kLVwRVEHR/YZ0onFUeQy', 'Coach',  16),
('manoj_coach',      '$2b$12$buKLsC701QmxzJrbeIG9guwqGcwFvZYrqfXrkQRi/Od9ZGKEXW1W.', 'Coach',  17),
('neha_admin',       '$2b$12$CBn5wvraXpWXJQC7gAyF8eNrPmqK3HWfwHA125Br6Ug3tcLLZzIUG', 'Admin',  19),
('amit_admin',       '$2b$12$frkwoaqCn3Qyk15NdOmU2OEolj9D23Rw2Z.HsycFpli7WKFW0BbE2', 'Admin',  20);
