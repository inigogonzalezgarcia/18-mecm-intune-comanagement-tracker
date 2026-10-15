-- MECM export for the co-management tracker.
-- Run read-only against the site database (CM_<SiteCode>) with an account that has db_datareader
-- or the "Read-only Analyst" role, then save the result as mecm_devices.csv (with header row).
--
-- Uses the supported reporting views. Adjust the collection names in the IN (...) list to the
-- collections in your plan.json: the co-management pilot collection and one collection per wave.
-- STRING_AGG needs SQL Server 2017 or later.

DECLARE @Collections TABLE (Name nvarchar(255));
INSERT INTO @Collections VALUES
    (N'CM - Co-management Pilot'),
    (N'W11 - Wave 0 Pilot'),
    (N'W11 - Wave 1'),
    (N'W11 - Wave 2');

SELECT
    s.Name0                                   AS name,
    s.ResourceID                              AS resource_id,
    ISNULL(s.Client0, 0)                      AS client,
    ISNULL(ch.ClientActiveStatus, 0)          AS client_active,
    CONVERT(varchar(33), ch.LastPolicyRequest, 126) AS last_policy_request,   -- ISO 8601, UTC in most sites
    s.Build01                                 AS os_build,                    -- e.g. 10.0.22631
    CAST(NULL AS int)                         AS win11_hw_ready,              -- see note below
    (
        SELECT STRING_AGG(c.Name, ';')
        FROM v_FullCollectionMembership fcm
        JOIN v_Collection c ON c.CollectionID = fcm.CollectionID
        WHERE fcm.ResourceID = s.ResourceID
          AND c.Name IN (SELECT Name FROM @Collections)
    )                                         AS collections
FROM v_R_System s
LEFT JOIN v_CH_ClientSummary ch ON ch.ResourceID = s.ResourceID
WHERE s.Operating_System_Name_and0 LIKE N'%Workstation%'
  AND ISNULL(s.Obsolete0, 0) = 0
  AND ISNULL(s.Decommissioned0, 0) = 0
ORDER BY s.Name0;

-- win11_hw_ready: there is no single standard view for this. Fill it (1/0) from whatever your
-- organisation uses: Endpoint analytics "Work from anywhere" / Windows 11 readiness report,
-- a hardware inventory extension (TPM 2.0, CPU on the supported list, Secure Boot), or a
-- spreadsheet from the hardware refresh plan. Leave it empty if unknown.
