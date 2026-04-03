-- ================================================================
-- OLYMPIA TRACK - SPORTS MANAGEMENT SYSTEM
-- CS 432: Assignment 1 (Module A)
-- ================================================================

DROP DATABASE IF EXISTS olympia_track;
CREATE DATABASE olympia_track;
USE olympia_track;

-- ==========================================
-- 1. INDEPENDENT ENTITIES (No Foreign Keys)
-- ==========================================

-- Table 1: Member
CREATE TABLE Member (
    MemberID      INT          PRIMARY KEY,
    Name          VARCHAR(100) NOT NULL,
    Image         VARCHAR(255),
    Age           INT          NOT NULL CHECK (Age > 0),
    Email         VARCHAR(100) NOT NULL UNIQUE,
    ContactNumber VARCHAR(15)  NOT NULL,
    Gender        ENUM('M','F','O') NOT NULL,
    Role          ENUM('Player','Coach','Admin') NOT NULL,
    JoinDate      DATE         NOT NULL
);

-- Table 2: Sport
CREATE TABLE Sport (
    SportID           INT          PRIMARY KEY,
    SportName         VARCHAR(50)  NOT NULL UNIQUE,
    Category          ENUM('Individual','Team','Dual') NOT NULL,
    MaxPlayersPerTeam INT          CHECK (MaxPlayersPerTeam > 0)
);

-- Table 3: Venue
CREATE TABLE Venue (
    VenueID     INT          PRIMARY KEY,
    VenueName   VARCHAR(100) NOT NULL,
    Location    VARCHAR(200) NOT NULL,
    Capacity    INT          CHECK (Capacity > 0),
    SurfaceType VARCHAR(30)
);

-- Table 4: Tournament
CREATE TABLE Tournament (
    TournamentID   INT PRIMARY KEY,
    TournamentName VARCHAR(100) NOT NULL,
    StartDate      DATE NOT NULL,
    EndDate        DATE NOT NULL,
    Description    VARCHAR(255),
    Status         ENUM('Upcoming', 'Ongoing', 'Completed') NOT NULL,
    CHECK (EndDate >= StartDate)
);

-- ==========================================
-- 2. DEPENDENT ENTITIES (Foreign Keys)
-- ==========================================

-- Table 5: Team
-- Includes CaptainID (FK) to enforce leadership structure
CREATE TABLE Team (
    TeamID     INT          PRIMARY KEY,
    TeamName   VARCHAR(50)  NOT NULL, 
    CoachID    INT,                   -- Nullable: Individual athletes might not have a coach
    CaptainID  INT,                   -- Nullable: Tracks the primary leader
    SportID    INT          NOT NULL,
    FormedDate DATE         NOT NULL,
    FOREIGN KEY (CoachID) REFERENCES Member(MemberID)
        ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (CaptainID) REFERENCES Member(MemberID)
        ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (SportID) REFERENCES Sport(SportID)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Table 6: TeamMember
-- Junction table: Members belong to Teams
-- Includes IsCaptain boolean for easy roster display
CREATE TABLE TeamMember (
    TeamID    INT          NOT NULL,
    MemberID  INT          NOT NULL,
    JoinDate  DATE         NOT NULL,
    Position  VARCHAR(30), 
    IsCaptain BOOLEAN      DEFAULT FALSE, 
    PRIMARY KEY (TeamID, MemberID),
    FOREIGN KEY (TeamID)   REFERENCES Team(TeamID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (MemberID) REFERENCES Member(MemberID)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 7: Event
-- Links to Tournament (M:1) and Venue (M:1)
CREATE TABLE Event (
    EventID      INT          PRIMARY KEY,
    EventName    VARCHAR(100) NOT NULL,
    TournamentID INT,                    -- Nullable for standalone matches
    EventDate    DATE         NOT NULL,
    StartTime    TIME         NOT NULL,
    EndTime      TIME         NOT NULL,
    VenueID      INT          NOT NULL,
    SportID      INT          NOT NULL,
    Status       ENUM('Scheduled','Ongoing','Completed','Cancelled') NOT NULL,
    Round        VARCHAR(50),            -- e.g., "Quarter-Final", "Heat 1"
    CHECK (EndTime > StartTime),
    FOREIGN KEY (TournamentID) REFERENCES Tournament(TournamentID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (VenueID)      REFERENCES Venue(VenueID)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (SportID)      REFERENCES Sport(SportID)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Table 8: Participation
-- Links a Team to an Event
-- Renamed 'Rank' to 'EventRank' to avoid keyword conflict
CREATE TABLE Participation (
    ParticipationID INT PRIMARY KEY,      
    TeamID          INT NOT NULL,
    EventID         INT NOT NULL,
    Score           VARCHAR(50),          
    EventRank       INT CHECK (EventRank >= 1), 
    Result          ENUM('Win', 'Loss', 'Draw', 'Qualified', 'Eliminated'),
    Remarks         VARCHAR(255),
    UNIQUE (TeamID, EventID),             -- Prevent double registration
    FOREIGN KEY (TeamID)  REFERENCES Team(TeamID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (EventID) REFERENCES Event(EventID)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- ==========================================
-- 3. LOGISTICS & TRACKING
-- ==========================================

-- Table 9: Equipment
-- Renamed 'Condition' to 'EquipmentCondition'
CREATE TABLE Equipment (
    EquipmentID        INT          PRIMARY KEY,
    EquipmentName      VARCHAR(50)  NOT NULL,
    TotalQuantity      INT          NOT NULL CHECK (TotalQuantity >= 0),
    EquipmentCondition ENUM('New','Good','Fair','Poor') NOT NULL,
    SportID            INT,         -- Nullable for generic items
    FOREIGN KEY (SportID) REFERENCES Sport(SportID)
        ON DELETE SET NULL ON UPDATE CASCADE
);

-- Table 10: EquipmentIssue
CREATE TABLE EquipmentIssue (
    IssueID     INT  PRIMARY KEY,
    EquipmentID INT  NOT NULL,
    MemberID    INT  NOT NULL,
    IssueDate   DATE NOT NULL,
    ReturnDate  DATE,
    Quantity    INT  NOT NULL CHECK (Quantity > 0),
    CHECK (ReturnDate IS NULL OR ReturnDate >= IssueDate),
    FOREIGN KEY (EquipmentID) REFERENCES Equipment(EquipmentID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (MemberID)    REFERENCES Member(MemberID)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 11: PracticeSession
CREATE TABLE PracticeSession (
    SessionID   INT  PRIMARY KEY,
    TeamID      INT  NOT NULL,
    VenueID     INT  NOT NULL,
    SessionDate DATE NOT NULL,
    StartTime   TIME NOT NULL,
    EndTime     TIME NOT NULL,
    CHECK (EndTime > StartTime),
    FOREIGN KEY (TeamID)  REFERENCES Team(TeamID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (VenueID) REFERENCES Venue(VenueID)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Table 12: PerformanceLog
CREATE TABLE PerformanceLog (
    LogID       INT           PRIMARY KEY,
    MemberID    INT           NOT NULL,
    SportID     INT           NOT NULL,
    MetricName  VARCHAR(50)   NOT NULL,
    MetricValue DECIMAL(10,2) NOT NULL,
    RecordDate  DATE          NOT NULL,
    FOREIGN KEY (MemberID) REFERENCES Member(MemberID)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (SportID)  REFERENCES Sport(SportID)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 13: MedicalRecord
-- Renamed 'Condition' to 'MedicalCondition'
CREATE TABLE MedicalRecord (
    RecordID         INT          PRIMARY KEY,
    MemberID         INT          NOT NULL,
    MedicalCondition VARCHAR(100) NOT NULL,
    DiagnosisDate    DATE         NOT NULL,
    RecoveryDate     DATE,
    Status           ENUM('Active','Recovered','Chronic') NOT NULL,
    CHECK (RecoveryDate IS NULL OR RecoveryDate >= DiagnosisDate),
    FOREIGN KEY (MemberID) REFERENCES Member(MemberID)
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- ================================================================
-- SAMPLE DATA INSERTION (Phase 4 Requirement)
-- ================================================================

-- 1. Member
INSERT INTO Member VALUES
(1,  'Aarav Sharma',    'img/aarav.jpg',    19, 'aarav.sharma@iitgn.ac.in',   '9876543201', 'M', 'Player', '2024-08-01'),
(2,  'Meera Patel',     'img/meera.jpg',    20, 'meera.patel@iitgn.ac.in',    '9876543202', 'F', 'Player', '2024-08-01'),
(3,  'Rohan Das',       'img/rohan.jpg',    21, 'rohan.das@iitgn.ac.in',      '9876543203', 'M', 'Player', '2024-08-15'),
(4,  'Priya Singh',     'img/priya.jpg',    19, 'priya.singh@iitgn.ac.in',    '9876543204', 'F', 'Player', '2024-09-01'),
(5,  'Arjun Mehta',     'img/arjun.jpg',    22, 'arjun.mehta@iitgn.ac.in',    '9876543205', 'M', 'Player', '2024-08-10'),
(6,  'Kavya Iyer',      'img/kavya.jpg',    20, 'kavya.iyer@iitgn.ac.in',     '9876543206', 'F', 'Player', '2024-08-20'),
(7,  'Vikash Yadav',    'img/vikash.jpg',   21, 'vikash.yadav@iitgn.ac.in',   '9876543207', 'M', 'Player', '2024-09-05'),
(8,  'Ananya Joshi',    'img/ananya.jpg',    19, 'ananya.joshi@iitgn.ac.in',   '9876543208', 'F', 'Player', '2024-09-10'),
(9,  'Siddharth Nair',  'img/siddharth.jpg',23, 'siddharth.nair@iitgn.ac.in', '9876543209', 'M', 'Player', '2024-08-05'),
(10, 'Riya Gupta',      'img/riya.jpg',     20, 'riya.gupta@iitgn.ac.in',     '9876543210', 'F', 'Player', '2024-08-25'),
(11, 'Harsh Pandey',    'img/harsh.jpg',    22, 'harsh.pandey@iitgn.ac.in',   '9876543211', 'M', 'Player', '2024-09-15'),
(12, 'Diya Kapoor',     'img/diya.jpg',     18, 'diya.kapoor@iitgn.ac.in',    '9876543212', 'F', 'Player', '2024-10-01'),
(13, 'Raj Kumar',       'img/raj.jpg',      38, 'raj.kumar@iitgn.ac.in',      '9876543213', 'M', 'Coach',  '2023-06-15'),
(14, 'Sunita Nair',     'img/sunita.jpg',   35, 'sunita.nair@iitgn.ac.in',    '9876543214', 'F', 'Coach',  '2023-07-01'),
(15, 'Deepak Verma',    'img/deepak.jpg',   42, 'deepak.verma@iitgn.ac.in',   '9876543215', 'M', 'Coach',  '2023-05-20'),
(16, 'Pooja Rathi',     'img/pooja.jpg',    36, 'pooja.rathi@iitgn.ac.in',    '9876543216', 'F', 'Coach',  '2023-08-10'),
(17, 'Manoj Tiwari',    'img/manoj.jpg',    45, 'manoj.tiwari@iitgn.ac.in',   '9876543217', 'M', 'Coach',  '2023-04-01'),
(18, 'Vikram Reddy',    'img/vikram.jpg',   40, 'vikram.reddy@iitgn.ac.in',   '9876543218', 'M', 'Admin',  '2023-01-10'),
(19, 'Neha Agarwal',    'img/neha.jpg',     32, 'neha.agarwal@iitgn.ac.in',   '9876543219', 'F', 'Admin',  '2023-02-15'),
(20, 'Amit Choudhary',  'img/amit.jpg',     34, 'amit.choudhary@iitgn.ac.in', '9876543220', 'M', 'Admin',  '2023-03-01');

-- 2. Sport
INSERT INTO Sport VALUES
(1, 'Athletics',  'Individual', NULL),
(2, 'Football',   'Team',       11),
(3, 'Badminton',  'Dual',       2),
(4, 'Cricket',    'Team',       11),
(5, 'Basketball', 'Team',       5),
(6, 'Tennis',     'Dual',       2),
(7, 'Volleyball', 'Team',       6),
(8, 'Swimming',   'Individual', NULL);

-- 3. Venue
INSERT INTO Venue VALUES
(1, 'Main Athletic Track',   'Central Sports Complex, IITGN', 2000, 'Synthetic'),
(2, 'Football Ground',       'North Campus, IITGN',           3000, 'Natural Grass'),
(3, 'Indoor Badminton Hall', 'Sports Block A, IITGN',         500,  'Wooden'),
(4, 'Cricket Stadium',       'East Campus, IITGN',            5000, 'Natural Grass'),
(5, 'Basketball Court',      'Sports Block B, IITGN',         800,  'Concrete'),
(6, 'Tennis Courts',         'South Campus, IITGN',           400,  'Clay'),
(7, 'Volleyball Arena',      'Sports Block A, IITGN',         600,  'Wooden'),
(8, 'Swimming Pool Complex', 'Aquatic Center, IITGN',         300,  'Tile');

-- 4. Tournament
INSERT INTO Tournament VALUES
(1, 'Winter Sports Championship', '2025-02-01', '2025-02-28', 'Internal college championship', 'Completed'),
(2, 'Inter-IIT Sports Meet',      '2025-03-01', '2025-03-20', 'Annual inter-college meet', 'Ongoing'),
(3, 'Summer Aquatics League',     '2025-04-01', '2025-04-15', 'Swimming and water sports', 'Upcoming');

-- 5. Team
INSERT INTO Team VALUES
-- Individual "Teams"
(1,  'Thunder Sprinters (Aarav)', 13, 1, 1, '2024-08-15'),
(2,  'Thunder Sprinters (Arjun)', 13, 5, 1, '2024-08-15'),
(3,  'Thunder Sprinters (Sid)',   13, 9, 1, '2024-08-15'),
(4,  'Shuttle Stars (Meera)',     14, 2, 3, '2024-08-20'),
(5,  'Shuttle Stars (Kavya)',     14, 6, 3, '2024-08-20'),
(6,  'Tennis Aces (Priya)',       16, 4, 6, '2024-09-05'),
(7,  'Tennis Aces (Ananya)',      16, 8, 6, '2024-09-05'),
(8,  'Aqua Sharks (Diya)',        14, 12, 8, '2024-09-15'),
-- Group Teams
(9,  'IITGN FC Alpha',            15, 7, 2, '2024-08-10'), 
(10, 'IITGN FC Beta',             15, 3, 2, '2024-10-01'), 
(11, 'Cricket XI Lions',          17, 11, 4, '2024-08-12'), 
(12, 'Hoop Warriors',             16, 1, 5, '2024-09-01'), 
(13, 'Volley Vipers',             13, 2, 7, '2024-09-10'), 
-- Doubles
(14, 'Shuttle Queens (Doubles)',  14, 2, 3, '2024-09-01'), 
(15, 'Tennis Duo (Doubles)',      16, 4, 6, '2024-09-01');

-- 6. TeamMember
INSERT INTO TeamMember VALUES
-- Individual
(1, 1,  '2024-08-15', 'Sprinter', TRUE),
(2, 5,  '2024-08-15', 'Sprinter', TRUE),
(3, 9,  '2024-08-15', 'Long Distance', TRUE),
(4, 2,  '2024-08-20', 'Singles', TRUE),
(5, 6,  '2024-08-20', 'Singles', TRUE),
(6, 4,  '2024-09-05', 'Singles', TRUE),
(7, 8,  '2024-09-05', 'Singles', TRUE),
(8, 12, '2024-09-15', 'Freestyle', TRUE),
-- Football
(9, 7,  '2024-08-10', 'Goalkeeper', TRUE),
(9, 3,  '2024-08-10', 'Forward', FALSE),
(9, 5,  '2024-08-10', 'Midfielder', FALSE),
(9, 11, '2024-08-10', 'Defender', FALSE),
-- Cricket
(11, 11, '2024-08-12', 'All-rounder', TRUE),
(11, 3,  '2024-08-12', 'Batsman', FALSE),
(11, 9,  '2024-08-12', 'Bowler', FALSE),
-- Basketball
(12, 1,  '2024-09-01', 'Point Guard', TRUE),
(12, 7,  '2024-09-01', 'Center', FALSE),
(12, 10, '2024-09-01', 'Shooting Guard', FALSE),
-- Doubles
(14, 2, '2024-09-01', 'Front Court', TRUE),
(14, 6, '2024-09-01', 'Back Court', FALSE),
(15, 4, '2024-09-01', 'Net Player', TRUE),
(15, 8, '2024-09-01', 'Base Player', FALSE);

-- 7. Event
INSERT INTO Event VALUES
(1,  '100m Sprint Finals',            1, '2025-02-15', '09:00:00', '10:30:00', 1, 1, 'Completed', 'Final'),
(2,  '200m Sprint Heats',             1, '2025-02-15', '11:00:00', '12:30:00', 1, 1, 'Completed', 'Heats'),
(3,  'Inter-College Football Match',  1, '2025-02-20', '14:00:00', '16:00:00', 2, 2, 'Completed', 'Group Stage'),
(4,  'Badminton Singles Open',        2, '2025-03-05', '10:00:00', '13:00:00', 3, 3, 'Completed', 'Final'),
(5,  'Badminton Doubles Championship',2, '2025-03-06', '10:00:00', '14:00:00', 3, 3, 'Completed', 'Final'),
(6,  'Cricket T20 League Match 1',    2, '2025-03-10', '09:00:00', '13:00:00', 4, 4, 'Completed', 'Group Stage'),
(7,  'Cricket T20 League Match 2',    2, '2025-03-12', '09:00:00', '13:00:00', 4, 4, 'Completed', 'Group Stage'),
(8,  'Basketball 3v3 Tournament',     2, '2025-03-15', '15:00:00', '18:00:00', 5, 5, 'Completed', 'Final'),
(9,  'Tennis Singles Open',           2, '2025-03-20', '08:00:00', '12:00:00', 6, 6, 'Ongoing',   'Semi-Final'),
(10, 'Volleyball Inter-Hostel',       2, '2025-03-25', '16:00:00', '19:00:00', 7, 7, 'Scheduled', 'Final'),
(11, '400m Relay Championship',       3, '2025-04-01', '10:00:00', '12:00:00', 1, 1, 'Scheduled', 'Final'),
(12, 'Football League Finals',        3, '2025-04-05', '14:00:00', '16:30:00', 2, 2, 'Scheduled', 'Final'),
(13, 'Swimming 50m Freestyle',        3, '2025-04-10', '09:00:00', '11:00:00', 8, 8, 'Scheduled', 'Final'),
(14, 'Annual Sports Day - Athletics', 3, '2025-04-20', '08:00:00', '17:00:00', 1, 1, 'Scheduled', 'All Day'),
(15, 'Cricket T20 Finals',            3, '2025-04-25', '09:00:00', '14:00:00', 4, 4, 'Scheduled', 'Final');

-- 8. Participation
INSERT INTO Participation VALUES
(1,  1,  1,  '10.85s',  1, 'Win', 'Gold medal - personal best'), 
(2,  2,  1,  '11.02s',  2, 'Loss', 'Silver medal'),               
(3,  3,  1,  '11.30s',  3, 'Loss', 'Bronze medal'),               
(4,  1,  2,  '21.50s',  2, 'Loss', 'Close finish'),
(5,  2,  2,  '21.20s',  1, 'Win', 'New campus record'),
(6,  9,  3,  '2 goals', 1, 'Win', 'Man of the match'),          
(7,  4,  4,  '21-15, 21-18', 1, 'Win', 'Won singles title'),     
(8,  5,  4,  '18-21, 21-19', 2, 'Loss', 'Runner-up'),            
(9,  14, 5,  '21-12, 21-16', 1, 'Win', 'Dominant doubles win'),  
(10, 11, 6,  '145 runs', 1, 'Win', 'High scoring game'),         
(11, 11, 7,  '120 runs', 2, 'Loss', 'Close defeat'),             
(12, 12, 8,  '18 pts',  1, 'Win', 'Tournament MVP'),             
(13, 6,  9,  '45 runs', NULL, 'Qualified', 'Reached finals'),     
(14, 7,  9,  '28 runs', NULL, 'Eliminated', 'Good effort'),       
(15, 13, 10, '3-1 Sets', NULL, 'Qualified', 'Semi-finals next'),  
(16, 9,  12, 'Pending', NULL, 'Qualified', 'Finals spot secured'), 
(17, 8,  13, '30.5s',   1, 'Win', 'School record'),               
(18, 1,  14, 'Participating', NULL, 'Qualified', NULL),
(19, 2,  14, 'Participating', NULL, 'Qualified', NULL),
(20, 11, 15, 'Pending', NULL, 'Qualified', 'Finals');

-- 9. Equipment
INSERT INTO Equipment VALUES
(1,  'Football',           20, 'Good', 2),
(2,  'Badminton Racket',   15, 'Good', 3),
(3,  'Shuttlecock (Box)',  30, 'New',  3),
(4,  'Cricket Bat',        10, 'Good', 4),
(5,  'Cricket Ball (Box)', 25, 'New',  4),
(6,  'Basketball',         12, 'Good', 5),
(7,  'Tennis Racket',       8, 'Fair', 6),
(8,  'Tennis Ball (Can)',  20, 'New',  6),
(9,  'Volleyball',         10, 'Good', 7),
(10, 'Swimming Goggles',   15, 'New',  8),
(11, 'Starting Blocks',     6, 'Good', 1),
(12, 'Stopwatch',          10, 'Good', NULL),
(13, 'First Aid Kit',       5, 'Good', NULL),
(14, 'Cone Markers (Set)', 20, 'New',  NULL),
(15, 'Resistance Bands',   12, 'New',  NULL);

-- 10. EquipmentIssue
INSERT INTO EquipmentIssue VALUES
(1,  1,  3,  '2025-02-18', '2025-02-20', 2),
(2,  2,  2,  '2025-03-01', '2025-03-05', 1),
(3,  3,  6,  '2025-03-01', '2025-03-06', 3),
(4,  4,  9,  '2025-03-08', '2025-03-13', 1),
(5,  5,  11, '2025-03-08', '2025-03-13', 2),
(6,  6,  1,  '2025-03-14', '2025-03-15', 2),
(7,  7,  4,  '2025-03-18', NULL,         1),
(8,  8,  8,  '2025-03-18', NULL,         2),
(9,  10, 12, '2025-04-01', NULL,         1),
(10, 11, 5,  '2025-02-14', '2025-02-15', 2),
(11, 12, 13, '2025-02-14', '2025-02-15', 3),
(12, 14, 15, '2025-02-10', '2025-02-20', 5),
(13, 1,  7,  '2025-02-19', '2025-02-20', 1),
(14, 9,  2,  '2025-03-24', NULL,         2),
(15, 13, 16, '2025-03-10', '2025-03-10', 1),
(16, 4,  3,  '2025-03-10', '2025-03-12', 2),
(17, 6,  10, '2025-03-14', '2025-03-15', 1),
(18, 15, 1,  '2025-03-20', NULL,         2);

-- 11. PracticeSession
INSERT INTO PracticeSession VALUES
(1,  1,  1, '2025-02-10', '06:00:00', '08:00:00'), 
(2,  2,  1, '2025-02-12', '06:00:00', '08:00:00'), 
(3,  9,  2, '2025-02-11', '16:00:00', '18:00:00'), 
(4,  9,  2, '2025-02-13', '16:00:00', '18:00:00'),
(5,  4,  3, '2025-02-25', '17:00:00', '19:00:00'), 
(6,  14, 3, '2025-03-01', '17:00:00', '19:00:00'), 
(7,  11, 4, '2025-03-05', '07:00:00', '10:00:00'), 
(8,  11, 4, '2025-03-08', '07:00:00', '10:00:00'),
(9,  12, 5, '2025-03-10', '15:00:00', '17:00:00'), 
(10, 12, 5, '2025-03-12', '15:00:00', '17:00:00'),
(11, 6,  6, '2025-03-15', '06:30:00', '08:30:00'), 
(12, 13, 7, '2025-03-18', '16:00:00', '18:00:00'), 
(13, 8,  8, '2025-03-20', '07:00:00', '09:00:00'), 
(14, 1,  1, '2025-03-25', '06:00:00', '08:00:00'),
(15, 9,  2, '2025-03-28', '16:00:00', '18:00:00'),
(16, 9,  2, '2025-03-30', '14:00:00', '16:00:00'),
(17, 11, 4, '2025-04-01', '07:00:00', '10:00:00'),
(18, 11, 4, '2025-04-03', '07:00:00', '10:00:00');

-- 12. PerformanceLog
INSERT INTO PerformanceLog VALUES
(1,  1,  1, '100m Time (s)',         10.85, '2025-02-15'),
(2,  1,  1, '200m Time (s)',         21.50, '2025-02-15'),
(3,  5,  1, '100m Time (s)',         11.02, '2025-02-15'),
(4,  5,  1, '200m Time (s)',         21.20, '2025-02-15'),
(5,  9,  1, '100m Time (s)',         11.30, '2025-02-15'),
(6,  1,  1, '100m Time (s)',         11.10, '2025-01-20'),
(7,  1,  1, '100m Time (s)',         10.95, '2025-02-01'),
(8,  3,  2, 'Goals Scored',           2.00, '2025-02-20'),
(9,  3,  4, 'Runs Scored',           45.00, '2025-03-10'),
(10, 9,  4, 'Wickets Taken',          3.00, '2025-03-10'),
(11, 11, 4, 'Runs Scored',           28.00, '2025-03-10'),
(12, 11, 4, 'Wickets Taken',          2.00, '2025-03-10'),
(13, 2,  3, 'Matches Won',            5.00, '2025-03-05'),
(14, 6,  3, 'Matches Won',            3.00, '2025-03-05'),
(15, 1,  5, 'Points Per Game',       18.00, '2025-03-15'),
(16, 7,  5, 'Points Per Game',       12.00, '2025-03-15'),
(17, 10, 5, 'Points Per Game',       15.00, '2025-03-15'),
(18, 12, 8, '50m Freestyle Time (s)',32.50, '2025-03-20'),
(19, 4,  6, 'Aces Per Match',         4.00, '2025-03-18'),
(20, 8,  6, 'Aces Per Match',         2.00, '2025-03-18');

-- 13. MedicalRecord
INSERT INTO MedicalRecord VALUES
(1,  1,  'Hamstring Strain',          '2025-01-10', '2025-01-25', 'Recovered'),
(2,  3,  'Ankle Sprain',              '2025-02-05', '2025-02-20', 'Recovered'),
(3,  5,  'Shin Splints',              '2025-01-15', '2025-02-10', 'Recovered'),
(4,  7,  'ACL Minor Tear',            '2025-02-25', '2025-04-25', 'Active'),
(5,  9,  'Shoulder Tendinitis',       '2025-03-01', '2025-03-20', 'Recovered'),
(6,  2,  'Wrist Sprain',              '2025-02-28', '2025-03-10', 'Recovered'),
(7,  11, 'Lower Back Pain',           '2025-03-05', NULL,         'Active'),
(8,  12, 'Swimmers Ear Infection',    '2025-03-18', '2025-03-25', 'Recovered'),
(9,  4,  'Tennis Elbow',              '2025-03-20', NULL,         'Active'),
(10, 6,  'Knee Bursitis',             '2024-11-10', '2025-01-15', 'Recovered'),
(11, 1,  'Mild Concussion',           '2025-03-15', '2025-03-22', 'Recovered'),
(12, 10, 'Stress Fracture (Foot)',    '2025-03-10', NULL,         'Active'),
(13, 8,  'Rotator Cuff Strain',       '2025-02-15', '2025-03-05', 'Recovered'),
(14, 3,  'Asthma (Exercise-induced)', '2024-08-15', NULL,         'Chronic'),
(15, 5,  'Plantar Fasciitis',         '2025-03-25', NULL,         'Active');

-- ================================================================
-- END OF SQL SCRIPT
-- ================================================================