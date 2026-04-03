USE olympia_track;

CREATE INDEX idx_eqissue_return_eq_qty 
    ON EquipmentIssue(ReturnDate, EquipmentID, Quantity);

CREATE INDEX idx_event_sportid_eventdate 
    ON Event(SportID, EventDate DESC);

-- Indices for member portfolio access:
CREATE INDEX idx_teammember_memberid 
    ON TeamMember(MemberID, TeamID);

CREATE INDEX idx_perflog_member_date 
    ON PerformanceLog(MemberID, RecordDate DESC);

CREATE INDEX idx_medical_member_date 
    ON MedicalRecord(MemberID, DiagnosisDate DESC);

-- Index for team page access:
CREATE INDEX idx_participation_team_event ON Participation(TeamID, EventID);

USE olympia_auth;

CREATE INDEX idx_audit_logid_asc ON audit_log(log_id ASC);

USE olympia_track;
