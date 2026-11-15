CREATE TABLE "code_tasks" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "requirement_id" INTEGER NOT NULL CHECK("requirement_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "design_revision_id" INTEGER NOT NULL CHECK("design_revision_id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "base_snapshot_id" INTEGER NOT NULL CHECK("base_snapshot_id" BETWEEN 1 AND 9007199254740991),
  "target_branch" TEXT NOT NULL CHECK(length("target_branch")>0),
  "execution_profile_version_id" INTEGER NOT NULL CHECK("execution_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "authorization_id" INTEGER NOT NULL CHECK("authorization_id" BETWEEN 1 AND 9007199254740991),
  "budget_limit_cny" TEXT NOT NULL CHECK(instr("budget_limit_cny",'.')=length("budget_limit_cny")-6 AND length("budget_limit_cny")>=8 AND "budget_limit_cny" NOT GLOB '*[^0-9.]*' AND substr("budget_limit_cny",-6) NOT GLOB '*[^0-9]*' AND instr(substr("budget_limit_cny",1,length("budget_limit_cny")-7),'.')=0 AND (substr("budget_limit_cny",1,1)<>'0' OR substr("budget_limit_cny",1,2)='0.')),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','WAITING','VERIFYING','AWAITING_TESTING','AWAITING_ACCEPTANCE','STOPPING','COMPLETED','TERMINATED')),
  "phase" TEXT NOT NULL CHECK("phase" IN ('PREPARING','BACKEND','FRONTEND','INTEGRATION','TESTING','ACCEPTANCE','DELIVERY','FINISHED')),
  "resume_phase" TEXT CHECK("resume_phase" IS NULL OR ("resume_phase" IN ('PREPARING','BACKEND','FRONTEND','INTEGRATION','TESTING','ACCEPTANCE','DELIVERY','FINISHED'))),
  "state_version" INTEGER NOT NULL CHECK("state_version" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "workspace_id" INTEGER CHECK("workspace_id" IS NULL OR ("workspace_id" BETWEEN 1 AND 9007199254740991)),
  "active_session_id" INTEGER CHECK("active_session_id" IS NULL OR ("active_session_id" BETWEEN 1 AND 9007199254740991)),
  "current_candidate_id" INTEGER CHECK("current_candidate_id" IS NULL OR ("current_candidate_id" BETWEEN 1 AND 9007199254740991)),
  "current_verification_id" INTEGER CHECK("current_verification_id" IS NULL OR ("current_verification_id" BETWEEN 1 AND 9007199254740991)),
  "current_test_report_id" INTEGER CHECK("current_test_report_id" IS NULL OR ("current_test_report_id" BETWEEN 1 AND 9007199254740991)),
  "current_delivery_plan_id" INTEGER CHECK("current_delivery_plan_id" IS NULL OR ("current_delivery_plan_id" BETWEEN 1 AND 9007199254740991)),
  "current_delivery_id" INTEGER CHECK("current_delivery_id" IS NULL OR ("current_delivery_id" BETWEEN 1 AND 9007199254740991)),
  "stop_requested_at" TEXT CHECK("stop_requested_at" IS NULL OR (length("stop_requested_at")=24 AND "stop_requested_at" GLOB '????-??-??T??:??:??.???Z')),
  "stopped_at" TEXT CHECK("stopped_at" IS NULL OR (length("stopped_at")=24 AND "stopped_at" GLOB '????-??-??T??:??:??.???Z')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "updated_at" TEXT NOT NULL CHECK(length("updated_at")=24 AND "updated_at" GLOB '????-??-??T??:??:??.???Z'),
  "started_at" TEXT CHECK("started_at" IS NULL OR (length("started_at")=24 AND "started_at" GLOB '????-??-??T??:??:??.???Z')),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  "last_observed_at" TEXT CHECK("last_observed_at" IS NULL OR (length("last_observed_at")=24 AND "last_observed_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,repository_id),
  FOREIGN KEY("active_session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("authorization_id") REFERENCES "code_authorizations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("base_snapshot_id") REFERENCES "code_snapshots"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_delivery_id") REFERENCES "code_deliveries"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_delivery_plan_id") REFERENCES "code_delivery_plans"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_test_report_id") REFERENCES "testing_reports"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_verification_id") REFERENCES "code_verifications"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("design_revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("execution_profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("requirement_id") REFERENCES "requirements"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("workspace_id") REFERENCES "code_workspaces"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id","requirement_id") REFERENCES "requirement_documents"("id","requirement_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("design_revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("active_session_id","id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("authorization_id","id") REFERENCES "code_authorizations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_candidate_id","id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_delivery_id","id") REFERENCES "code_deliveries"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_delivery_plan_id","id") REFERENCES "code_delivery_plans"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_verification_id","id") REFERENCES "code_verifications"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("workspace_id","id") REFERENCES "code_workspaces"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("base_snapshot_id","repository_id") REFERENCES "code_snapshots"("id","repository_id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((status<>'WAITING' OR resume_phase IS NOT NULL) IS TRUE),
  CHECK((status<>'STOPPING' OR stop_requested_at IS NOT NULL) IS TRUE),
  CHECK((status<>'TERMINATED' OR (stopped_at IS NOT NULL AND ended_at IS NOT NULL)) IS TRUE),
  CHECK((status<>'COMPLETED' OR (ended_at IS NOT NULL AND phase='FINISHED')) IS TRUE),
  CHECK((stopped_at IS NULL OR (stop_requested_at IS NOT NULL AND stopped_at>=stop_requested_at)) IS TRUE),
  CHECK((status<>'COMPLETED' OR stop_requested_at IS NULL) IS TRUE),
  CHECK((status<>'TERMINATED' OR phase='FINISHED') IS TRUE),
  CHECK((budget_limit_cny<>'0.000000') IS TRUE),
  CHECK((status NOT IN ('VERIFYING','AWAITING_TESTING','AWAITING_ACCEPTANCE') OR current_candidate_id IS NOT NULL) IS TRUE),
  CHECK((status<>'AWAITING_ACCEPTANCE' OR current_test_report_id IS NOT NULL) IS TRUE),
  CHECK((status<>'RUNNING' OR (active_session_id IS NOT NULL AND started_at IS NOT NULL)) IS TRUE),
  CHECK((status<>'COMPLETED' OR current_delivery_id IS NOT NULL) IS TRUE)
) STRICT;

CREATE TABLE "code_snapshots" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "registration_operation_id" INTEGER NOT NULL CHECK("registration_operation_id" BETWEEN 1 AND 9007199254740991),
  "content_profile_version_id" INTEGER NOT NULL CHECK("content_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "commit_oid" TEXT NOT NULL CHECK(length("commit_oid") IN (40,64) AND "commit_oid" NOT GLOB '*[^0-9a-f]*'),
  "content_tree_oid" TEXT NOT NULL CHECK(length("content_tree_oid") IN (40,64) AND "content_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "retention_ref" TEXT NOT NULL CHECK(length("retention_ref")>0),
  "content_policy_version" TEXT NOT NULL CHECK("content_policy_version"='GIT20-BASELINE-1'),
  "registered_at" TEXT NOT NULL CHECK(length("registered_at")=24 AND "registered_at" GLOB '????-??-??T??:??:??.???Z'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(registration_operation_id),
  UNIQUE(repository_id,retention_ref),
  UNIQUE(id,repository_id),
  FOREIGN KEY("registration_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((retention_ref='refs/walle/baselines/'||id) IS TRUE),
  CHECK((created_at>=registered_at) IS TRUE)
) STRICT;

CREATE TABLE "code_candidates" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "base_snapshot_id" INTEGER NOT NULL CHECK("base_snapshot_id" BETWEEN 1 AND 9007199254740991),
  "capture_operation_id" INTEGER NOT NULL CHECK("capture_operation_id" BETWEEN 1 AND 9007199254740991),
  "content_store_key" TEXT NOT NULL CHECK(length("content_store_key")>0),
  "content_tree_oid" TEXT NOT NULL CHECK(length("content_tree_oid") IN (40,64) AND "content_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "parent_candidate_id" INTEGER CHECK("parent_candidate_id" IS NULL OR ("parent_candidate_id" BETWEEN 1 AND 9007199254740991)),
  "role" TEXT NOT NULL CHECK("role" IN ('BACKEND','FRONTEND','INTEGRATION')),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "content_policy_version" TEXT NOT NULL CHECK(length("content_policy_version")>0),
  "manifest_sha256" TEXT NOT NULL CHECK(length("manifest_sha256")=64 AND "manifest_sha256" NOT GLOB '*[^0-9a-f]*'),
  "captured_at" TEXT NOT NULL CHECK(length("captured_at")=24 AND "captured_at" GLOB '????-??-??T??:??:??.???Z'),
  "published_for_testing_at" TEXT CHECK("published_for_testing_at" IS NULL OR (length("published_for_testing_at")=24 AND "published_for_testing_at" GLOB '????-??-??T??:??:??.???Z')),
  "publication_operation_id" INTEGER CHECK("publication_operation_id" IS NULL OR ("publication_operation_id" BETWEEN 1 AND 9007199254740991)),
  "file_count" INTEGER NOT NULL CHECK("file_count" BETWEEN 0 AND 9007199254740991),
  "byte_count" INTEGER NOT NULL CHECK("byte_count" BETWEEN 0 AND 9007199254740991),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(capture_operation_id),
  UNIQUE(publication_operation_id),
  FOREIGN KEY("base_snapshot_id") REFERENCES "code_snapshots"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("capture_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("capture_operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("parent_candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("parent_candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("publication_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("publication_operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((published_for_testing_at IS NULL)=(publication_operation_id IS NULL)) IS TRUE),
  CHECK((created_at>=captured_at) IS TRUE),
  CHECK((content_policy_version='CONTENT20-STORE-1') IS TRUE)
) STRICT;

CREATE TABLE "code_defects" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "candidate_id" INTEGER NOT NULL CHECK("candidate_id" BETWEEN 1 AND 9007199254740991),
  "actual_behavior" TEXT NOT NULL CHECK(length("actual_behavior")>0),
  "expected_behavior" TEXT NOT NULL CHECK(length("expected_behavior")>0),
  "basis_ref" TEXT NOT NULL CHECK(json_valid("basis_ref") AND json_type("basis_ref")='object'),
  "testing_finding_id" INTEGER CHECK("testing_finding_id" IS NULL OR ("testing_finding_id" BETWEEN 1 AND 9007199254740991)),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "actor_ref" TEXT NOT NULL CHECK(length("actor_ref")>0),
  "basis_document_id" INTEGER GENERATED ALWAYS AS (json_extract(basis_ref,'$.document_id')) STORED NOT NULL,
  "basis_revision_id" INTEGER GENERATED ALWAYS AS (json_extract(basis_ref,'$.revision_id')) STORED NOT NULL,
  CHECK((basis_ref IS NULL OR (json_type(basis_ref,'$.document_id')='integer' AND json_type(basis_ref,'$.revision_id')='integer' AND json_type(basis_ref,'$.quote')='text' AND length(json_extract(basis_ref,'$.quote'))>0)) IS TRUE),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_finding_id") REFERENCES "testing_findings"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("basis_document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("basis_revision_id","basis_document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_repairs" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "source_candidate_id" INTEGER NOT NULL CHECK("source_candidate_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "result_candidate_id" INTEGER CHECK("result_candidate_id" IS NULL OR ("result_candidate_id" BETWEEN 1 AND 9007199254740991)),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  "failure_code" TEXT CHECK("failure_code" IS NULL OR (length("failure_code")>0)),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("result_candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("result_candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("source_candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("source_candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_delivery_plans" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "candidate_id" INTEGER NOT NULL CHECK("candidate_id" BETWEEN 1 AND 9007199254740991),
  "test_report_id" INTEGER NOT NULL CHECK("test_report_id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "target_branch" TEXT NOT NULL CHECK(length("target_branch")>0),
  "expected_target_commit" TEXT NOT NULL CHECK(length("expected_target_commit") IN (40,64) AND "expected_target_commit" NOT GLOB '*[^0-9a-f]*'),
  "target_tree_oid" TEXT NOT NULL CHECK(length("target_tree_oid") IN (40,64) AND "target_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "target_content_store_key" TEXT NOT NULL CHECK(length("target_content_store_key")>0),
  "target_manifest_sha256" TEXT NOT NULL CHECK(length("target_manifest_sha256")=64 AND "target_manifest_sha256" NOT GLOB '*[^0-9a-f]*'),
  "result_tree_oid" TEXT NOT NULL CHECK(length("result_tree_oid") IN (40,64) AND "result_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,task_id,candidate_id,test_report_id),
  FOREIGN KEY("candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_report_id") REFERENCES "testing_reports"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id","repository_id") REFERENCES "code_tasks"("id","repository_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_acceptances" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "candidate_id" INTEGER NOT NULL CHECK("candidate_id" BETWEEN 1 AND 9007199254740991),
  "test_report_id" INTEGER NOT NULL CHECK("test_report_id" BETWEEN 1 AND 9007199254740991),
  "delivery_plan_id" INTEGER NOT NULL CHECK("delivery_plan_id" BETWEEN 1 AND 9007199254740991),
  "manual_risk_accepted" INTEGER NOT NULL CHECK("manual_risk_accepted" IN (0,1)),
  "actor_ref" TEXT NOT NULL CHECK(length("actor_ref")>0),
  "accepted_at" TEXT NOT NULL CHECK(length("accepted_at")=24 AND "accepted_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,task_id,delivery_plan_id),
  FOREIGN KEY("candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("delivery_plan_id") REFERENCES "code_delivery_plans"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("delivery_plan_id","task_id") REFERENCES "code_delivery_plans"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_report_id") REFERENCES "testing_reports"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("delivery_plan_id","task_id","candidate_id","test_report_id") REFERENCES "code_delivery_plans"("id","task_id","candidate_id","test_report_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_deliveries" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "acceptance_id" INTEGER NOT NULL CHECK("acceptance_id" BETWEEN 1 AND 9007199254740991),
  "delivery_plan_id" INTEGER NOT NULL CHECK("delivery_plan_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','PREPARING','WRITING','UNKNOWN','SUCCEEDED','BLOCKED','CANCELLED')),
  "git_write_status" TEXT NOT NULL CHECK("git_write_status" IN ('NOT_DISPATCHED','PREPARED','MAY_HAVE_BEEN_SENT','CONFIRMED','ABORTED_UNSENT','UNKNOWN')),
  "postcheck_status" TEXT NOT NULL CHECK("postcheck_status" IN ('NOT_RUN','VERIFIED','CONFLICT','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "current_window_id" INTEGER CHECK("current_window_id" IS NULL OR ("current_window_id" BETWEEN 1 AND 9007199254740991)),
  "commit_input_ref" TEXT CHECK("commit_input_ref" IS NULL OR (length("commit_input_ref")>0)),
  "commit_input_sha256" TEXT CHECK("commit_input_sha256" IS NULL OR (length("commit_input_sha256")=64 AND "commit_input_sha256" NOT GLOB '*[^0-9a-f]*')),
  "observed_target_commit" TEXT CHECK("observed_target_commit" IS NULL OR (length("observed_target_commit") IN (40,64) AND "observed_target_commit" NOT GLOB '*[^0-9a-f]*')),
  "delivered_at" TEXT CHECK("delivered_at" IS NULL OR (length("delivered_at")=24 AND "delivered_at" GLOB '????-??-??T??:??:??.???Z')),
  "last_reconciled_at" TEXT CHECK("last_reconciled_at" IS NULL OR (length("last_reconciled_at")=24 AND "last_reconciled_at" GLOB '????-??-??T??:??:??.???Z')),
  "planned_commit_oid" TEXT CHECK("planned_commit_oid" IS NULL OR (length("planned_commit_oid") IN (40,64) AND "planned_commit_oid" NOT GLOB '*[^0-9a-f]*')),
  "failure_code" TEXT CHECK("failure_code" IS NULL OR (length("failure_code")>0)),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(acceptance_id),
  FOREIGN KEY("acceptance_id") REFERENCES "code_acceptances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("acceptance_id","task_id") REFERENCES "code_acceptances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_window_id") REFERENCES "code_delivery_windows"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("delivery_plan_id") REFERENCES "code_delivery_plans"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("delivery_plan_id","task_id") REFERENCES "code_delivery_plans"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("acceptance_id","task_id","delivery_plan_id") REFERENCES "code_acceptances"("id","task_id","delivery_plan_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_window_id","id") REFERENCES "code_delivery_windows"("id","delivery_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_delivery_windows" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "delivery_id" INTEGER NOT NULL CHECK("delivery_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "confirmed_at" TEXT NOT NULL CHECK(length("confirmed_at")=24 AND "confirmed_at" GLOB '????-??-??T??:??:??.???Z'),
  "expires_at" TEXT NOT NULL CHECK(length("expires_at")=24 AND "expires_at" GLOB '????-??-??T??:??:??.???Z'),
  "controller_epoch_ref" TEXT NOT NULL CHECK(length("controller_epoch_ref")>0),
  PRIMARY KEY("id"),
  UNIQUE(delivery_id,operation_id),
  UNIQUE(id,delivery_id),
  FOREIGN KEY("delivery_id") REFERENCES "code_deliveries"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_workspaces" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "base_snapshot_id" INTEGER NOT NULL CHECK("base_snapshot_id" BETWEEN 1 AND 9007199254740991),
  "private_location_key" TEXT NOT NULL CHECK(length("private_location_key")>0),
  "status" TEXT NOT NULL CHECK("status" IN ('PREPARING','READY','UNKNOWN','RELEASED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "ready_at" TEXT CHECK("ready_at" IS NULL OR (length("ready_at")=24 AND "ready_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(task_id),
  FOREIGN KEY("base_snapshot_id") REFERENCES "code_snapshots"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_instances" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "workspace_id" INTEGER NOT NULL CHECK("workspace_id" BETWEEN 1 AND 9007199254740991),
  "executor_version" TEXT NOT NULL CHECK(length("executor_version")>0),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "effective_profile_version_id" INTEGER NOT NULL CHECK("effective_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "status" TEXT NOT NULL CHECK("status" IN ('STARTING','READY','STOPPING','STOPPED','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "process_identity" TEXT CHECK("process_identity" IS NULL OR (json_valid("process_identity") AND json_type("process_identity")='object')),
  "runtime_binding" TEXT CHECK("runtime_binding" IS NULL OR (json_valid("runtime_binding") AND json_type("runtime_binding")='object')),
  "connection_ref" TEXT CHECK("connection_ref" IS NULL OR (length("connection_ref")>0)),
  "native_storage_ref" TEXT CHECK("native_storage_ref" IS NULL OR (length("native_storage_ref")>0)),
  "ready_at" TEXT CHECK("ready_at" IS NULL OR (length("ready_at")=24 AND "ready_at" GLOB '????-??-??T??:??:??.???Z')),
  "stopped_at" TEXT CHECK("stopped_at" IS NULL OR (length("stopped_at")=24 AND "stopped_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("effective_profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("workspace_id") REFERENCES "code_workspaces"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("workspace_id","task_id") REFERENCES "code_workspaces"("id","task_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_sessions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "instance_id" INTEGER NOT NULL CHECK("instance_id" BETWEEN 1 AND 9007199254740991),
  "role" TEXT NOT NULL CHECK("role" IN ('BACKEND','FRONTEND','INTEGRATION')),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "status" TEXT NOT NULL CHECK("status" IN ('PREPARING','ACTIVE','QUIESCING','RETIRED','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "native_session_id" TEXT CHECK("native_session_id" IS NULL OR (length("native_session_id")>0)),
  "native_message_id" TEXT CHECK("native_message_id" IS NULL OR (length("native_message_id")>0)),
  "gateway_credential_ref" TEXT CHECK("gateway_credential_ref" IS NULL OR (length("gateway_credential_ref")>0)),
  "model_window" TEXT CHECK("model_window" IS NULL OR (json_valid("model_window") AND json_type("model_window")='object')),
  "last_observed_at" TEXT CHECK("last_observed_at" IS NULL OR (length("last_observed_at")=24 AND "last_observed_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("instance_id") REFERENCES "code_instances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id","task_id") REFERENCES "code_instances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_commands" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "purpose" TEXT NOT NULL CHECK("purpose" IN ('EXECUTION','CHECK','SERVICE','CONTROL_GIT')),
  "command_ref" TEXT NOT NULL CHECK(length("command_ref")>0),
  "config_version_id" INTEGER CHECK("config_version_id" IS NULL OR ("config_version_id" BETWEEN 1 AND 9007199254740991)),
  "testing_profile_version_id" INTEGER CHECK("testing_profile_version_id" IS NULL OR ("testing_profile_version_id" BETWEEN 1 AND 9007199254740991)),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "session_id" INTEGER CHECK("session_id" IS NULL OR ("session_id" BETWEEN 1 AND 9007199254740991)),
  "verification_item_id" INTEGER CHECK("verification_item_id" IS NULL OR ("verification_item_id" BETWEEN 1 AND 9007199254740991)),
  "process_identity" TEXT CHECK("process_identity" IS NULL OR (json_valid("process_identity") AND json_type("process_identity")='object')),
  "runtime_binding" TEXT CHECK("runtime_binding" IS NULL OR (json_valid("runtime_binding") AND json_type("runtime_binding")='object')),
  "exit_code" INTEGER,
  "started_at" TEXT CHECK("started_at" IS NULL OR (length("started_at")=24 AND "started_at" GLOB '????-??-??T??:??:??.???Z')),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  FOREIGN KEY("config_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","testing_task_id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id","task_id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("verification_item_id") REFERENCES "code_verification_items"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((task_id IS NULL)=(config_version_id IS NULL)) IS TRUE),
  CHECK(((testing_task_id IS NULL)=(testing_profile_version_id IS NULL)) IS TRUE)
) STRICT;

CREATE TABLE "code_execution_records" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "instance_id" INTEGER NOT NULL CHECK("instance_id" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "kind" TEXT NOT NULL CHECK("kind" IN ('MESSAGE','TOOL','COMMAND_OUTPUT','CONTROL','ERROR')),
  "text" TEXT NOT NULL CHECK(length("text")>0),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  "session_id" INTEGER CHECK("session_id" IS NULL OR ("session_id" BETWEEN 1 AND 9007199254740991)),
  "native_event_id" TEXT CHECK("native_event_id" IS NULL OR (length("native_event_id")>0)),
  "source_kind" TEXT CHECK("source_kind" IS NULL OR ("source_kind" IN ('OPERATION','COMMAND','QUESTION','PERMISSION','LLM_USE'))),
  "source_id" INTEGER CHECK("source_id" IS NULL OR ("source_id" BETWEEN 1 AND 9007199254740991)),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("instance_id") REFERENCES "code_instances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id","task_id") REFERENCES "code_instances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id","task_id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((source_kind IS NULL)=(source_id IS NULL)) IS TRUE)
) STRICT;

CREATE TABLE "code_operations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "resource_kind" TEXT NOT NULL CHECK("resource_kind" IN ('TASK','TESTING_TASK','TEST_PLAN','TEST_PLAN_VERSION','TEST_PACK_VERSION','TEST_PROFILE_VERSION','TEST_AUTHORIZATION','TEST_REPORT','TESTING_FINDING','REPOSITORY','SNAPSHOT','EXECUTION_PROFILE','EXECUTION_PROFILE_VERSION','CHECK_SET','CHECK_SET_VERSION','AUTHORIZATION')),
  "resource_id" INTEGER NOT NULL CHECK("resource_id" BETWEEN 1 AND 9007199254740991),
  "session_id" INTEGER CHECK("session_id" IS NULL OR ("session_id" BETWEEN 1 AND 9007199254740991)),
  "operation_type" TEXT NOT NULL CHECK("operation_type" IN ('ANSWER_QUESTION','APPLY_CONFIGURATION','APPROVE_AUTHORIZATION','ATTACH_ASSETS','CAPTURE_AND_CHECK','CREATE_CHECK_SET','CREATE_EXECUTION_PROFILE','CREATE_PLAN','DECIDE_PERMISSION','DELIVER','DRAFT_PLAN','EDIT_PLAN','HANDOFF_ROLE','INCREASE_TEST_BUDGET','LINK_TEST_REPORT','PREPARE_DELIVERY','PREPARE_HANDOFF','PUBLISH_CHECK_SET','PUBLISH_EXECUTION_PROFILE','PUBLISH_PACK','PUBLISH_PLAN','RECONCILE','REFRESH_REPOSITORY','REGISTER_BASE','REGISTER_REPOSITORY','REPAIR','RESUME','REVIEW_FINDING','REVOKE_PACK','REVOKE_PLAN','RUN_TEST','SEAL_PACK','START','SUBMIT_FOR_TESTING','TERMINATE','VALIDATE_PACK','VERIFY_CANDIDATE')),
  "idempotency_key" TEXT NOT NULL CHECK(length("idempotency_key")>0),
  "expected_state_version" INTEGER CHECK("expected_state_version" IS NULL OR ("expected_state_version" BETWEEN 1 AND 9007199254740991)),
  "fixed_input" TEXT NOT NULL CHECK(json_valid("fixed_input") AND json_type("fixed_input")='object'),
  "control_generation" INTEGER CHECK("control_generation" IS NULL OR ("control_generation" BETWEEN 1 AND 9007199254740991)),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "started_at" TEXT CHECK("started_at" IS NULL OR (length("started_at")=24 AND "started_at" GLOB '????-??-??T??:??:??.???Z')),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  "failure_code" TEXT CHECK("failure_code" IS NULL OR ("failure_code" IN ('INVALID_INPUT','CHECK_CONFIGURATION_INVALID','BASIS_REF_INVALID','DEFECT_SOURCE_MISMATCH','BUDGET_NOT_INCREASED','NOT_FOUND','AUTHORIZATION_NOT_APPLICABLE','PERMISSION_NOT_GRANTED','DELIVERY_NOT_AUTHORIZED','COMMAND_CLOSED','VERSION_CONFLICT','ACTIVE_TASK_EXISTS','INVALID_STATE','TASK_ENDED','OPERATION_CONFLICT','OPERATION_IN_PROGRESS','RESOURCE_CONFLICT','TEST_REPORT_NOT_ELIGIBLE','TEST_SOURCE_MISMATCH','TEST_ASSET_REVOKED','VERIFICATION_STAGE_NOT_READY','SOURCE_CHANGED','SOURCE_BUSY','SOURCE_UNSUPPORTED','PRECONDITION_FAILED','BASIS_NOT_CONFIRMED','EXTERNAL_RESULT_UNKNOWN','EXECUTION_NOT_STOPPED','QUESTION_NOT_OPEN','SESSION_NOT_CURRENT','WRITER_ACTIVE','CONTENT_NOT_READY','CANDIDATE_NOT_CURRENT','CHECKS_NOT_PASSED','HANDOFF_CHECKS_NOT_PASSED','DELIVERY_PLAN_STALE','TARGET_CHANGED','TARGET_CHECKED_OUT','DELIVERY_WINDOW_REQUIRED','REPOSITORY_UNSUPPORTED','CONFIG_NOT_READY','STORAGE_UNAVAILABLE','INTERNAL_ERROR','EVIDENCE_INCOMPLETE'))),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  FOREIGN KEY("session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id","task_id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((resource_kind='TASK' AND task_id IS NOT NULL AND testing_task_id IS NULL AND resource_id=task_id AND expected_state_version IS NOT NULL AND control_generation IS NOT NULL) OR (resource_kind='TESTING_TASK' AND testing_task_id IS NOT NULL AND task_id IS NULL AND resource_id=testing_task_id AND expected_state_version IS NOT NULL AND control_generation IS NOT NULL) OR (resource_kind NOT IN ('TASK','TESTING_TASK') AND task_id IS NULL AND testing_task_id IS NULL AND control_generation IS NULL)) IS TRUE)
) STRICT;

CREATE TABLE "code_operation_steps" (
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "step_no" INTEGER NOT NULL CHECK("step_no" BETWEEN 1 AND 9007199254740991),
  "step_type" TEXT NOT NULL CHECK("step_type" IN ('ABORT_IF_APPLICABLE','APPLY_PAIR','BLOCK_NEW','BUILD_CONTEXT','BUILD_OBJECTS','CALL_MODEL','CAPTURE','CAPTURE_RESULT','CHECK','CHECK_CONDITIONS','CLEANUP','COMPARE','COMPILE','CONFIRM_NATIVE','CONTINUE_OR_OBSERVE','CREATE_CHILD_TASKS','CREATE_SESSION','DISPATCH_COMMIT_ONCE','EXECUTE','FENCE','FINALIZE_OWNED_RUNTIME','FIX_COMMIT_INPUT','FIX_INPUT','FIX_REFERENCE_SET','MATERIALIZE','OBSERVE','OBSERVE_CHILDREN','PIN_COMMIT','PREPARE','PREPARE_BASIS','PREPARE_REF','PUBLISH','QUERY','QUIESCE','QUIESCE_IF_REQUIRED','READ_NATIVE','READ_REPOSITORY','READ_TARGET','RECONCILE','RECONCILE_WRITES','RECORD','RESERVE','RESTORE_CHECK_COPY','RESTORE_SOURCE','RESTORE_WORKSPACE','REVOKE','REVOKE_GATEWAY','SAVE_BASELINE','SAVE_DRAFT','SAVE_FACT','SAVE_OBSERVATION','SAVE_PACK','SAVE_PLAN','SAVE_PLANNED_COMMIT','SAVE_REPORT','SAVE_TERMINATED','SAVE_VALIDATION','SEAL','SEAL_TARGET','SEND_HANDOFF','SEND_INITIAL','SEND_REPAIR','SEND_RESPONSE','START_INSTANCE','STOP','STOP_OWNED_ACTIVITY','STOP_OWN_ACTIVITIES','VALIDATE','VALIDATE_COMMIT','VALIDATE_PLAN','VALIDATE_REPORT','VERIFY_EFFECTIVE','VERIFY_INPUT','VERIFY_LOCKED_TARGET','VERIFY_PINNED_OBJECTS','VERIFY_STOP')),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
  "external_identity" TEXT CHECK("external_identity" IS NULL OR (json_valid("external_identity") AND json_type("external_identity")='object')),
  "fixed_input" TEXT NOT NULL CHECK(json_valid("fixed_input") AND json_type("fixed_input")='object'),
  "result_ref" TEXT CHECK("result_ref" IS NULL OR (json_valid("result_ref") AND json_type("result_ref")='object')),
  "started_at" TEXT CHECK("started_at" IS NULL OR (length("started_at")=24 AND "started_at" GLOB '????-??-??T??:??:??.???Z')),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  "last_observed_at" TEXT CHECK("last_observed_at" IS NULL OR (length("last_observed_at")=24 AND "last_observed_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("operation_id","step_no"),
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_waiting_items" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "kind" TEXT NOT NULL CHECK("kind" IN ('PREPARATION','QUESTION','PERMISSION','BUDGET','MODEL_RESULT','OPERATION_RESULT','CHECK_FAILURE','CHECK_ENVIRONMENT','CHECK_RESULT','CONFIGURATION','TARGET_CHANGED','DELIVERY_RESULT')),
  "source_kind" TEXT NOT NULL CHECK("source_kind" IN ('OPERATION','QUESTION','PERMISSION','VERIFICATION_ITEM','LLM_USE','DELIVERY')),
  "source_id" INTEGER NOT NULL CHECK("source_id" BETWEEN 1 AND 9007199254740991),
  "resume_phase" TEXT NOT NULL CHECK("resume_phase" IN ('PREPARING','BACKEND','FRONTEND','INTEGRATION','TESTING','ACCEPTANCE','DELIVERY','FINISHED','PLAN','PREPARE','EXECUTE','REPORT')),
  "status" TEXT NOT NULL CHECK("status" IN ('OPEN','RESOLVED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "resolved_at" TEXT CHECK("resolved_at" IS NULL OR (length("resolved_at")=24 AND "resolved_at" GLOB '????-??-??T??:??:??.???Z')),
  "resolution_ref" TEXT CHECK("resolution_ref" IS NULL OR (json_valid("resolution_ref") AND json_type("resolution_ref")='object')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_execution_profile_versions" (
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "check_set_version_id" INTEGER NOT NULL CHECK("check_set_version_id" BETWEEN 1 AND 9007199254740991),
  "version" INTEGER NOT NULL CHECK("version" BETWEEN 1 AND 9007199254740991),
  "profile_id" INTEGER NOT NULL CHECK("profile_id" BETWEEN 1 AND 9007199254740991),
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "executor" TEXT NOT NULL CHECK(json_valid("executor") AND json_type("executor")='object'),
  "git" TEXT NOT NULL CHECK(json_valid("git") AND json_type("git")='object'),
  "models" TEXT NOT NULL CHECK(json_valid("models") AND json_type("models")='object'),
  "environment" TEXT NOT NULL CHECK(json_valid("environment") AND json_type("environment")='object'),
  "commands" TEXT NOT NULL CHECK(json_valid("commands") AND json_type("commands")='array'),
  "capture_rules" TEXT NOT NULL CHECK(json_valid("capture_rules") AND json_type("capture_rules")='object'),
  "delivery" TEXT CHECK("delivery" IS NULL OR (json_valid("delivery") AND json_type("delivery")='object')),
  "limits" TEXT NOT NULL CHECK(json_valid("limits") AND json_type("limits")='object'),
  "capability_evidence_refs" TEXT NOT NULL CHECK(json_valid("capability_evidence_refs") AND json_type("capability_evidence_refs")='array'),
  PRIMARY KEY("id"),
  UNIQUE(profile_id,version),
  FOREIGN KEY("check_set_version_id") REFERENCES "code_check_set_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("profile_id") REFERENCES "code_execution_profiles"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_verifications" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "owner_kind" TEXT NOT NULL CHECK("owner_kind" IN ('CODING','TESTING')),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "candidate_id" INTEGER CHECK("candidate_id" IS NULL OR ("candidate_id" BETWEEN 1 AND 9007199254740991)),
  "snapshot_id" INTEGER CHECK("snapshot_id" IS NULL OR ("snapshot_id" BETWEEN 1 AND 9007199254740991)),
  "purpose" TEXT NOT NULL CHECK("purpose" IN ('HANDOFF','DIAGNOSTIC','ACCEPTANCE','PACK_VALIDATION')),
  "role" TEXT CHECK("role" IS NULL OR ("role" IN ('BACKEND','FRONTEND','INTEGRATION'))),
  "check_set_version_id" INTEGER NOT NULL CHECK("check_set_version_id" BETWEEN 1 AND 9007199254740991),
  "profile_version_id" INTEGER CHECK("profile_version_id" IS NULL OR ("profile_version_id" BETWEEN 1 AND 9007199254740991)),
  "testing_profile_version_id" INTEGER CHECK("testing_profile_version_id" IS NULL OR ("testing_profile_version_id" BETWEEN 1 AND 9007199254740991)),
  "environment_record_id" INTEGER NOT NULL CHECK("environment_record_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "scope_stages" TEXT NOT NULL CHECK(json_valid("scope_stages") AND json_type("scope_stages")='array'),
  "selected_check_ids" TEXT NOT NULL CHECK(json_valid("selected_check_ids") AND json_type("selected_check_ids")='array'),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','RUNNING','FINISHED','UNKNOWN','CANCELLED')),
  "stop_status" TEXT NOT NULL CHECK("stop_status" IN ('NOT_STARTED','ACTIVE','VERIFIED','UNKNOWN')),
  "cleanup_status" TEXT NOT NULL CHECK("cleanup_status" IN ('NOT_STARTED','CLEANING','VERIFIED','FAILED','UNKNOWN')),
  "source_integrity_status" TEXT NOT NULL CHECK("source_integrity_status" IN ('NOT_CHECKED','VERIFIED','CHANGED','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  "backend_handoff_operation_id" INTEGER CHECK("backend_handoff_operation_id" IS NULL OR ("backend_handoff_operation_id" BETWEEN 1 AND 9007199254740991)),
  "frontend_handoff_operation_id" INTEGER CHECK("frontend_handoff_operation_id" IS NULL OR ("frontend_handoff_operation_id" BETWEEN 1 AND 9007199254740991)),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  FOREIGN KEY("backend_handoff_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("backend_handoff_operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("backend_handoff_operation_id","testing_task_id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id","task_id") REFERENCES "code_candidates"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("check_set_version_id") REFERENCES "code_check_set_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("environment_record_id") REFERENCES "code_environment_records"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("environment_record_id","task_id") REFERENCES "code_environment_records"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("environment_record_id","testing_task_id") REFERENCES "code_environment_records"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("frontend_handoff_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("frontend_handoff_operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("frontend_handoff_operation_id","testing_task_id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","testing_task_id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("snapshot_id") REFERENCES "code_snapshots"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((candidate_id IS NULL)<>(snapshot_id IS NULL)) IS TRUE),
  CHECK(((owner_kind='CODING' AND task_id IS NOT NULL AND testing_task_id IS NULL AND candidate_id IS NOT NULL AND profile_version_id IS NOT NULL AND testing_profile_version_id IS NULL AND role IS NOT NULL AND purpose='HANDOFF') OR (owner_kind='TESTING' AND testing_task_id IS NOT NULL AND task_id IS NULL AND profile_version_id IS NULL AND testing_profile_version_id IS NOT NULL AND role IS NULL AND backend_handoff_operation_id IS NULL AND frontend_handoff_operation_id IS NULL AND purpose IN ('DIAGNOSTIC','ACCEPTANCE','PACK_VALIDATION'))) IS TRUE),
  CHECK((owner_kind<>'CODING' OR (role='BACKEND' AND backend_handoff_operation_id IS NULL AND frontend_handoff_operation_id IS NULL AND json_array_length(scope_stages)=1 AND json_extract(scope_stages,'$[0]')='BACKEND') OR (role='FRONTEND' AND backend_handoff_operation_id IS NOT NULL AND frontend_handoff_operation_id IS NULL AND json_array_length(scope_stages)=2 AND json_extract(scope_stages,'$[0]')='BACKEND' AND json_extract(scope_stages,'$[1]')='FRONTEND') OR (role='INTEGRATION' AND backend_handoff_operation_id IS NOT NULL AND frontend_handoff_operation_id IS NOT NULL AND json_array_length(scope_stages)=3 AND json_extract(scope_stages,'$[0]')='BACKEND' AND json_extract(scope_stages,'$[1]')='FRONTEND' AND json_extract(scope_stages,'$[2]')='INTEGRATION')) IS TRUE)
) STRICT;

CREATE TABLE "code_verification_items" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "verification_id" INTEGER NOT NULL CHECK("verification_id" BETWEEN 1 AND 9007199254740991),
  "check_id" TEXT NOT NULL CHECK(length("check_id")>0),
  "required" INTEGER NOT NULL CHECK("required" IN (0,1)),
  "check_kind" TEXT NOT NULL CHECK("check_kind" IN ('PROJECT_COMMAND','CONTROLLED_ASSERTION')),
  "evidence_kind" TEXT NOT NULL CHECK("evidence_kind" IN ('PROCESS_EXIT','CONTROLLED_CASES','CONTENT_INTEGRITY')),
  "command_execution_id" INTEGER CHECK("command_execution_id" IS NULL OR ("command_execution_id" BETWEEN 1 AND 9007199254740991)),
  "result" TEXT NOT NULL CHECK("result" IN ('NOT_RUN','RUNNING','PASSED','FAILED','UNAVAILABLE','UNKNOWN','CANCELLED')),
  "reason_code" TEXT CHECK("reason_code" IS NULL OR ("reason_code" IN ('COMMAND_FAILED','ASSERTION_FAILED','NO_CONTROLLED_CASES','RESOURCE_MISSING','DEPENDENCY_MISMATCH','ISOLATION_UNAVAILABLE','TARGET_UNVERIFIED','APPLICATION_START_FAILED','TIMEOUT','OUTPUT_LIMIT','INPUT_CHANGED','EVIDENCE_INCOMPLETE','PROCESS_STATE_UNKNOWN','CLEANUP_UNVERIFIED'))),
  "expected_case_count" INTEGER CHECK("expected_case_count" IS NULL OR ("expected_case_count" BETWEEN 0 AND 9007199254740991)),
  "executed_case_count" INTEGER CHECK("executed_case_count" IS NULL OR ("executed_case_count" BETWEEN 0 AND 9007199254740991)),
  "passed_case_count" INTEGER CHECK("passed_case_count" IS NULL OR ("passed_case_count" BETWEEN 0 AND 9007199254740991)),
  "failed_case_count" INTEGER CHECK("failed_case_count" IS NULL OR ("failed_case_count" BETWEEN 0 AND 9007199254740991)),
  "reused_from_item_id" INTEGER CHECK("reused_from_item_id" IS NULL OR ("reused_from_item_id" BETWEEN 1 AND 9007199254740991)),
  "evidence_summary" TEXT CHECK("evidence_summary" IS NULL OR (length("evidence_summary")>0)),
  "started_at" TEXT CHECK("started_at" IS NULL OR (length("started_at")=24 AND "started_at" GLOB '????-??-??T??:??:??.???Z')),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(verification_id,check_id),
  FOREIGN KEY("command_execution_id") REFERENCES "code_commands"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("reused_from_item_id") REFERENCES "code_verification_items"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("verification_id") REFERENCES "code_verifications"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((evidence_kind='CONTROLLED_CASES' AND expected_case_count IS NOT NULL AND executed_case_count IS NOT NULL AND passed_case_count IS NOT NULL AND failed_case_count IS NOT NULL AND executed_case_count=passed_case_count+failed_case_count AND executed_case_count<=expected_case_count) OR (evidence_kind<>'CONTROLLED_CASES' AND expected_case_count IS NULL AND executed_case_count IS NULL AND passed_case_count IS NULL AND failed_case_count IS NULL)) IS TRUE),
  CHECK((result<>'PASSED' OR evidence_kind<>'CONTROLLED_CASES' OR (executed_case_count=expected_case_count AND expected_case_count>0)) IS TRUE)
) STRICT;

CREATE TABLE "code_verification_case_results" (
  "item_id" INTEGER NOT NULL CHECK("item_id" BETWEEN 1 AND 9007199254740991),
  "case_id" TEXT NOT NULL CHECK(length("case_id")>0),
  "result" TEXT NOT NULL CHECK("result" IN ('PASSED','FAILED')),
  "assertion_results" TEXT NOT NULL CHECK(json_valid("assertion_results") AND json_type("assertion_results")='array'),
  "capture_status" TEXT NOT NULL CHECK("capture_status" IN ('FULL','REDACTED')),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("item_id","case_id"),
  FOREIGN KEY("item_id") REFERENCES "code_verification_items"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_environment_records" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "runtime_refs" TEXT NOT NULL CHECK(json_valid("runtime_refs") AND json_type("runtime_refs")='array'),
  "dependency_refs" TEXT NOT NULL CHECK(json_valid("dependency_refs") AND json_type("dependency_refs")='array'),
  "runner_refs" TEXT NOT NULL CHECK(json_valid("runner_refs") AND json_type("runner_refs")='array'),
  "effective_config_application_id" INTEGER CHECK("effective_config_application_id" IS NULL OR ("effective_config_application_id" BETWEEN 1 AND 9007199254740991)),
  "testing_profile_version_id" INTEGER CHECK("testing_profile_version_id" IS NULL OR ("testing_profile_version_id" BETWEEN 1 AND 9007199254740991)),
  "check_resource_refs" TEXT NOT NULL CHECK(json_valid("check_resource_refs") AND json_type("check_resource_refs")='array'),
  "scope_key" TEXT NOT NULL CHECK(length("scope_key")>0),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  FOREIGN KEY("effective_config_application_id") REFERENCES "code_configuration_applications"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("effective_config_application_id","task_id") REFERENCES "code_configuration_applications"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_model_response_frames" (
  "llm_use_id" INTEGER NOT NULL CHECK("llm_use_id" BETWEEN 1 AND 9007199254740991),
  "seq" INTEGER NOT NULL CHECK("seq" BETWEEN 1 AND 9007199254740991),
  "received_at" TEXT NOT NULL CHECK(length("received_at")=24 AND "received_at" GLOB '????-??-??T??:??:??.???Z'),
  "frame_json" TEXT NOT NULL CHECK(json_valid("frame_json") AND json_type("frame_json")='object'),
  "capture_status" TEXT NOT NULL CHECK("capture_status" IN ('FULL','REDACTED','INCOMPLETE')),
  PRIMARY KEY("llm_use_id","seq"),
  FOREIGN KEY("llm_use_id") REFERENCES "llm_uses"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_task_reservations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "llm_use_id" INTEGER NOT NULL CHECK("llm_use_id" BETWEEN 1 AND 9007199254740991),
  "price_version_id" INTEGER NOT NULL CHECK("price_version_id" BETWEEN 1 AND 9007199254740991),
  "reserved_cny" TEXT NOT NULL CHECK(instr("reserved_cny",'.')=length("reserved_cny")-6 AND length("reserved_cny")>=8 AND "reserved_cny" NOT GLOB '*[^0-9.]*' AND substr("reserved_cny",-6) NOT GLOB '*[^0-9]*' AND instr(substr("reserved_cny",1,length("reserved_cny")-7),'.')=0 AND (substr("reserved_cny",1,1)<>'0' OR substr("reserved_cny",1,2)='0.')),
  "status" TEXT NOT NULL CHECK("status" IN ('RESERVED','SETTLED','RELEASED_UNSENT','UNKNOWN','DISPUTED')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "settled_cny" TEXT CHECK("settled_cny" IS NULL OR (instr("settled_cny",'.')=length("settled_cny")-6 AND length("settled_cny")>=8 AND "settled_cny" NOT GLOB '*[^0-9.]*' AND substr("settled_cny",-6) NOT GLOB '*[^0-9]*' AND instr(substr("settled_cny",1,length("settled_cny")-7),'.')=0 AND (substr("settled_cny",1,1)<>'0' OR substr("settled_cny",1,2)='0.'))),
  "settled_at" TEXT CHECK("settled_at" IS NULL OR (length("settled_at")=24 AND "settled_at" GLOB '????-??-??T??:??:??.???Z')),
  "settlement_basis" TEXT CHECK("settlement_basis" IS NULL OR ("settlement_basis" IN ('VERIFIED_USAGE','PROVIDER_BILL'))),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  UNIQUE(llm_use_id),
  FOREIGN KEY("llm_use_id") REFERENCES "llm_uses"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("llm_use_id","testing_task_id") REFERENCES "llm_uses"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("price_version_id") REFERENCES "model_price_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((settled_cny IS NULL AND settled_at IS NULL AND settlement_basis IS NULL) OR (settled_cny IS NOT NULL AND settled_at IS NOT NULL AND settlement_basis IS NOT NULL)) IS TRUE),
  CHECK((status<>'SETTLED' OR settled_cny IS NOT NULL) IS TRUE)
) STRICT;

CREATE TABLE "model_price_versions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "model_profile_ref" TEXT NOT NULL CHECK(length("model_profile_ref")>0),
  "model_snapshot_ref" TEXT NOT NULL CHECK(length("model_snapshot_ref")>0),
  "channel" TEXT NOT NULL CHECK("channel" IN ('ARK_CN_BEIJING')),
  "billing_scope_ref" TEXT NOT NULL CHECK(length("billing_scope_ref")>0),
  "service_tier" TEXT NOT NULL CHECK("service_tier"='default'),
  "valid_from" TEXT NOT NULL CHECK(length("valid_from")=24 AND "valid_from" GLOB '????-??-??T??:??:??.???Z'),
  "valid_until" TEXT CHECK("valid_until" IS NULL OR (length("valid_until")=24 AND "valid_until" GLOB '????-??-??T??:??:??.???Z')),
  "currency" TEXT NOT NULL CHECK("currency"='CNY'),
  "input_price_per_million" TEXT NOT NULL CHECK(instr("input_price_per_million",'.')=length("input_price_per_million")-6 AND length("input_price_per_million")>=8 AND "input_price_per_million" NOT GLOB '*[^0-9.]*' AND substr("input_price_per_million",-6) NOT GLOB '*[^0-9]*' AND instr(substr("input_price_per_million",1,length("input_price_per_million")-7),'.')=0 AND (substr("input_price_per_million",1,1)<>'0' OR substr("input_price_per_million",1,2)='0.')),
  "output_price_per_million" TEXT NOT NULL CHECK(instr("output_price_per_million",'.')=length("output_price_per_million")-6 AND length("output_price_per_million")>=8 AND "output_price_per_million" NOT GLOB '*[^0-9.]*' AND substr("output_price_per_million",-6) NOT GLOB '*[^0-9]*' AND instr(substr("output_price_per_million",1,length("output_price_per_million")-7),'.')=0 AND (substr("output_price_per_million",1,1)<>'0' OR substr("output_price_per_million",1,2)='0.')),
  "cache_price_rules" TEXT NOT NULL CHECK(json_valid("cache_price_rules") AND json_type("cache_price_rules")='array'),
  "tariff_rules" TEXT NOT NULL CHECK(json_valid("tariff_rules") AND json_type("tariff_rules")='object'),
  "rounding_rule" TEXT NOT NULL CHECK("rounding_rule"='TOTAL_HALF_UP_6DP'),
  "source_ref" TEXT NOT NULL CHECK(length("source_ref")>0),
  "verified_at" TEXT NOT NULL CHECK(length("verified_at")=24 AND "verified_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id")
) STRICT;

CREATE TABLE "model_usage_evidence" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "llm_use_id" INTEGER NOT NULL CHECK("llm_use_id" BETWEEN 1 AND 9007199254740991),
  "external_evidence_id" TEXT NOT NULL CHECK(length("external_evidence_id")>0),
  "source_ref" TEXT NOT NULL CHECK(length("source_ref")>0),
  "usage" TEXT NOT NULL CHECK(json_valid("usage") AND json_type("usage")='object'),
  "received_at" TEXT NOT NULL CHECK(length("received_at")=24 AND "received_at" GLOB '????-??-??T??:??:??.???Z'),
  "status" TEXT NOT NULL CHECK("status" IN ('VERIFIED','REJECTED','DISPUTED')),
  PRIMARY KEY("id"),
  UNIQUE(source_ref,external_evidence_id),
  FOREIGN KEY("llm_use_id") REFERENCES "llm_uses"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_questions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "session_id" INTEGER NOT NULL CHECK("session_id" BETWEEN 1 AND 9007199254740991),
  "instance_id" INTEGER NOT NULL CHECK("instance_id" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "native_question_id" TEXT NOT NULL CHECK(length("native_question_id")>0),
  "questions" TEXT NOT NULL CHECK(json_valid("questions") AND json_type("questions")='array'),
  "status" TEXT NOT NULL CHECK("status" IN ('OPEN','ANSWERING','RESOLVED','REJECTED','UNKNOWN','OBSOLETE')),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  "resolved_at" TEXT CHECK("resolved_at" IS NULL OR (length("resolved_at")=24 AND "resolved_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(instance_id,session_id,native_question_id),
  FOREIGN KEY("instance_id") REFERENCES "code_instances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id","task_id") REFERENCES "code_instances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id","task_id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_permissions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "session_id" INTEGER NOT NULL CHECK("session_id" BETWEEN 1 AND 9007199254740991),
  "instance_id" INTEGER NOT NULL CHECK("instance_id" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "native_permission_id" TEXT NOT NULL CHECK(length("native_permission_id")>0),
  "tool_name" TEXT NOT NULL CHECK(length("tool_name")>0),
  "patterns" TEXT NOT NULL CHECK(json_valid("patterns") AND json_type("patterns")='array'),
  "object_refs" TEXT NOT NULL CHECK(json_valid("object_refs") AND json_type("object_refs")='array'),
  "requested_action" TEXT NOT NULL CHECK("requested_action" IN ('READ','WRITE','EXECUTE','NETWORK','UNKNOWN')),
  "tool_ref" TEXT CHECK("tool_ref" IS NULL OR (json_valid("tool_ref") AND json_type("tool_ref")='object')),
  "native_observation" TEXT CHECK("native_observation" IS NULL OR (json_valid("native_observation") AND json_type("native_observation")='object')),
  "status" TEXT NOT NULL CHECK("status" IN ('OPEN','ANSWERING','RESOLVED','REJECTED','UNKNOWN','OBSOLETE')),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  "resolved_at" TEXT CHECK("resolved_at" IS NULL OR (length("resolved_at")=24 AND "resolved_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(instance_id,session_id,native_permission_id),
  FOREIGN KEY("instance_id") REFERENCES "code_instances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id","task_id") REFERENCES "code_instances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id") REFERENCES "code_sessions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("session_id","task_id") REFERENCES "code_sessions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_question_handoffs" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "question_id" INTEGER NOT NULL CHECK("question_id" BETWEEN 1 AND 9007199254740991),
  "target_document_id" INTEGER NOT NULL CHECK("target_document_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("question_id") REFERENCES "code_questions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("question_id","task_id") REFERENCES "code_questions"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_question_handoff_events" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "handoff_id" INTEGER NOT NULL CHECK("handoff_id" BETWEEN 1 AND 9007199254740991),
  "kind" TEXT NOT NULL CHECK("kind" IN ('PREPARED','DISCUSSION_LINKED','REVISION_LINKED','ABANDONED')),
  "guide_run_id" INTEGER CHECK("guide_run_id" IS NULL OR ("guide_run_id" BETWEEN 1 AND 9007199254740991)),
  "message_id" INTEGER CHECK("message_id" IS NULL OR ("message_id" BETWEEN 1 AND 9007199254740991)),
  "revision_id" INTEGER CHECK("revision_id" IS NULL OR ("revision_id" BETWEEN 1 AND 9007199254740991)),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  FOREIGN KEY("guide_run_id") REFERENCES "guide_runs"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("handoff_id") REFERENCES "code_question_handoffs"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("message_id") REFERENCES "conversation_messages"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_repositories" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "name" TEXT NOT NULL CHECK(length("name")>0),
  "canonical_root" TEXT NOT NULL CHECK(length("canonical_root")>0),
  "git_common_dir" TEXT NOT NULL CHECK(length("git_common_dir")>0),
  "object_format" TEXT NOT NULL CHECK("object_format" IN ('sha1','sha256')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(git_common_dir)
) STRICT;

CREATE TABLE "code_repository_observations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "head_commit" TEXT CHECK("head_commit" IS NULL OR (length("head_commit") IN (40,64) AND "head_commit" NOT GLOB '*[^0-9a-f]*')),
  "local_branches" TEXT NOT NULL CHECK(json_valid("local_branches") AND json_type("local_branches")='array'),
  "worktrees" TEXT NOT NULL CHECK(json_valid("worktrees") AND json_type("worktrees")='array'),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  "status" TEXT NOT NULL CHECK("status" IN ('READABLE','UNAVAILABLE','UNKNOWN')),
  PRIMARY KEY("id"),
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_tasks" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "kind" TEXT NOT NULL CHECK("kind" IN ('PRODUCT','PACK_VALIDATION')),
  "requirement_id" INTEGER NOT NULL CHECK("requirement_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "design_revision_id" INTEGER NOT NULL CHECK("design_revision_id" BETWEEN 1 AND 9007199254740991),
  "target_kind" TEXT NOT NULL CHECK("target_kind" IN ('CANDIDATE','SNAPSHOT')),
  "candidate_id" INTEGER CHECK("candidate_id" IS NULL OR ("candidate_id" BETWEEN 1 AND 9007199254740991)),
  "snapshot_id" INTEGER CHECK("snapshot_id" IS NULL OR ("snapshot_id" BETWEEN 1 AND 9007199254740991)),
  "purpose" TEXT NOT NULL CHECK("purpose" IN ('DIAGNOSTIC','ACCEPTANCE','PACK_VALIDATION')),
  "plan_version_id" INTEGER CHECK("plan_version_id" IS NULL OR ("plan_version_id" BETWEEN 1 AND 9007199254740991)),
  "test_pack_version_id" INTEGER CHECK("test_pack_version_id" IS NULL OR ("test_pack_version_id" BETWEEN 1 AND 9007199254740991)),
  "profile_version_id" INTEGER NOT NULL CHECK("profile_version_id" BETWEEN 1 AND 9007199254740991),
  "authorization_id" INTEGER NOT NULL CHECK("authorization_id" BETWEEN 1 AND 9007199254740991),
  "budget_limit_cny" TEXT NOT NULL CHECK(instr("budget_limit_cny",'.')=length("budget_limit_cny")-6 AND length("budget_limit_cny")>=8 AND "budget_limit_cny" NOT GLOB '*[^0-9.]*' AND substr("budget_limit_cny",-6) NOT GLOB '*[^0-9]*' AND instr(substr("budget_limit_cny",1,length("budget_limit_cny")-7),'.')=0 AND (substr("budget_limit_cny",1,1)<>'0' OR substr("budget_limit_cny",1,2)='0.')),
  "status" TEXT NOT NULL CHECK("status" IN ('DRAFT','PLANNING','READY','RUNNING','WAITING','STOPPING','COMPLETED','TERMINATED')),
  "phase" TEXT NOT NULL CHECK("phase" IN ('PLAN','PREPARE','EXECUTE','REPORT','FINISHED')),
  "state_version" INTEGER NOT NULL CHECK("state_version" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "current_verification_id" INTEGER CHECK("current_verification_id" IS NULL OR ("current_verification_id" BETWEEN 1 AND 9007199254740991)),
  "draft_plan_operation_id" INTEGER CHECK("draft_plan_operation_id" IS NULL OR ("draft_plan_operation_id" BETWEEN 1 AND 9007199254740991)),
  "active_operation_id" INTEGER CHECK("active_operation_id" IS NULL OR ("active_operation_id" BETWEEN 1 AND 9007199254740991)),
  "report_id" INTEGER CHECK("report_id" IS NULL OR ("report_id" BETWEEN 1 AND 9007199254740991)),
  "previous_testing_task_id" INTEGER CHECK("previous_testing_task_id" IS NULL OR ("previous_testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "validation_id" INTEGER CHECK("validation_id" IS NULL OR ("validation_id" BETWEEN 1 AND 9007199254740991)),
  "stop_requested_at" TEXT CHECK("stop_requested_at" IS NULL OR (length("stop_requested_at")=24 AND "stop_requested_at" GLOB '????-??-??T??:??:??.???Z')),
  "stopped_at" TEXT CHECK("stopped_at" IS NULL OR (length("stopped_at")=24 AND "stopped_at" GLOB '????-??-??T??:??:??.???Z')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  FOREIGN KEY("active_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("authorization_id") REFERENCES "testing_authorizations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("candidate_id") REFERENCES "code_candidates"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_verification_id") REFERENCES "code_verifications"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("design_revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("draft_plan_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("plan_version_id") REFERENCES "testing_plan_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("previous_testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("report_id") REFERENCES "testing_reports"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("requirement_id") REFERENCES "requirements"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("snapshot_id") REFERENCES "code_snapshots"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_pack_version_id") REFERENCES "testing_pack_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("validation_id") REFERENCES "testing_pack_validations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id","requirement_id") REFERENCES "requirement_documents"("id","requirement_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("design_revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("active_operation_id","id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("authorization_id","id") REFERENCES "testing_authorizations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("current_verification_id","id") REFERENCES "code_verifications"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("draft_plan_operation_id","id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("report_id","id") REFERENCES "testing_reports"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_pack_version_id","plan_version_id") REFERENCES "testing_pack_versions"("id","plan_version_id") DEFERRABLE INITIALLY DEFERRED,
  CHECK(((target_kind='CANDIDATE' AND candidate_id IS NOT NULL AND snapshot_id IS NULL) OR (target_kind='SNAPSHOT' AND snapshot_id IS NOT NULL AND candidate_id IS NULL)) IS TRUE),
  CHECK(((kind='PACK_VALIDATION')=(validation_id IS NOT NULL)) IS TRUE),
  CHECK(((plan_version_id IS NULL)=(test_pack_version_id IS NULL)) IS TRUE),
  CHECK((status<>'STOPPING' OR stop_requested_at IS NOT NULL) IS TRUE),
  CHECK((status<>'TERMINATED' OR (stopped_at IS NOT NULL AND ended_at IS NOT NULL)) IS TRUE),
  CHECK((status<>'COMPLETED' OR (report_id IS NOT NULL AND ended_at IS NOT NULL AND phase='FINISHED')) IS TRUE)
) STRICT;

CREATE TABLE "testing_plans" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "name" TEXT NOT NULL CHECK(length("name")>0),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id")
) STRICT;

CREATE TABLE "testing_plan_versions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "plan_id" INTEGER NOT NULL CHECK("plan_id" BETWEEN 1 AND 9007199254740991),
  "version" INTEGER NOT NULL CHECK("version" BETWEEN 1 AND 9007199254740991),
  "requirement_id" INTEGER NOT NULL CHECK("requirement_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "design_revision_id" INTEGER NOT NULL CHECK("design_revision_id" BETWEEN 1 AND 9007199254740991),
  "behaviors" TEXT NOT NULL CHECK(json_valid("behaviors") AND json_type("behaviors")='array'),
  "cases" TEXT NOT NULL CHECK(json_valid("cases") AND json_type("cases")='array'),
  "unresolved_questions" TEXT NOT NULL CHECK(json_valid("unresolved_questions") AND json_type("unresolved_questions")='array'),
  "status" TEXT NOT NULL CHECK("status" IN ('DRAFT','PUBLISHED','REVOKED')),
  "state_version" INTEGER NOT NULL CHECK("state_version" BETWEEN 1 AND 9007199254740991),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "published_at" TEXT CHECK("published_at" IS NULL OR (length("published_at")=24 AND "published_at" GLOB '????-??-??T??:??:??.???Z')),
  "revoked_at" TEXT CHECK("revoked_at" IS NULL OR (length("revoked_at")=24 AND "revoked_at" GLOB '????-??-??T??:??:??.???Z')),
  "revocation_reason" TEXT CHECK("revocation_reason" IS NULL OR (length("revocation_reason")>0)),
  PRIMARY KEY("id"),
  UNIQUE(plan_id,version),
  FOREIGN KEY("design_revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("plan_id") REFERENCES "testing_plans"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("requirement_id") REFERENCES "requirements"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("document_id","requirement_id") REFERENCES "requirement_documents"("id","requirement_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("design_revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_pack_versions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "plan_version_id" INTEGER NOT NULL CHECK("plan_version_id" BETWEEN 1 AND 9007199254740991),
  "version" INTEGER NOT NULL CHECK("version" BETWEEN 1 AND 9007199254740991),
  "check_set_version_id" INTEGER CHECK("check_set_version_id" IS NULL OR ("check_set_version_id" BETWEEN 1 AND 9007199254740991)),
  "content_ref" TEXT CHECK("content_ref" IS NULL OR (length("content_ref")>0)),
  "sha256" TEXT CHECK("sha256" IS NULL OR (length("sha256")=64 AND "sha256" NOT GLOB '*[^0-9a-f]*')),
  "status" TEXT NOT NULL CHECK("status" IN ('DRAFT','SEALED','PUBLISHED','REVOKED')),
  "validation_id" INTEGER CHECK("validation_id" IS NULL OR ("validation_id" BETWEEN 1 AND 9007199254740991)),
  "state_version" INTEGER NOT NULL CHECK("state_version" BETWEEN 1 AND 9007199254740991),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "published_at" TEXT CHECK("published_at" IS NULL OR (length("published_at")=24 AND "published_at" GLOB '????-??-??T??:??:??.???Z')),
  "revoked_at" TEXT CHECK("revoked_at" IS NULL OR (length("revoked_at")=24 AND "revoked_at" GLOB '????-??-??T??:??:??.???Z')),
  "revocation_reason" TEXT CHECK("revocation_reason" IS NULL OR (length("revocation_reason")>0)),
  PRIMARY KEY("id"),
  UNIQUE(plan_version_id,version),
  UNIQUE(id,plan_version_id),
  FOREIGN KEY("check_set_version_id") REFERENCES "code_check_set_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("plan_version_id") REFERENCES "testing_plan_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("validation_id") REFERENCES "testing_pack_validations"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_pack_validations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "test_pack_version_id" INTEGER NOT NULL CHECK("test_pack_version_id" BETWEEN 1 AND 9007199254740991),
  "profile_version_id" INTEGER NOT NULL CHECK("profile_version_id" BETWEEN 1 AND 9007199254740991),
  "reference_set_ref" TEXT NOT NULL CHECK(length("reference_set_ref")>0),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "result" TEXT NOT NULL CHECK("result" IN ('PENDING','RUNNING','PASSED','FAILED','UNAVAILABLE','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "ended_at" TEXT CHECK("ended_at" IS NULL OR (length("ended_at")=24 AND "ended_at" GLOB '????-??-??T??:??:??.???Z')),
  PRIMARY KEY("id"),
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_pack_version_id") REFERENCES "testing_pack_versions"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_reports" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "testing_task_id" INTEGER NOT NULL CHECK("testing_task_id" BETWEEN 1 AND 9007199254740991),
  "verification_id" INTEGER NOT NULL CHECK("verification_id" BETWEEN 1 AND 9007199254740991),
  "plan_version_id" INTEGER NOT NULL CHECK("plan_version_id" BETWEEN 1 AND 9007199254740991),
  "test_pack_version_id" INTEGER NOT NULL CHECK("test_pack_version_id" BETWEEN 1 AND 9007199254740991),
  "input_fingerprint" TEXT NOT NULL CHECK(length("input_fingerprint")=64 AND "input_fingerprint" NOT GLOB '*[^0-9a-f]*'),
  "result" TEXT NOT NULL CHECK("result" IN ('PASSED','FAILED','UNAVAILABLE','UNKNOWN','CANCELLED','INCONCLUSIVE')),
  "scope_stages" TEXT NOT NULL CHECK(json_valid("scope_stages") AND json_type("scope_stages")='array'),
  "manual_coverage_ids" TEXT NOT NULL CHECK(json_valid("manual_coverage_ids") AND json_type("manual_coverage_ids")='array'),
  "uncovered_behavior_ids" TEXT NOT NULL CHECK(json_valid("uncovered_behavior_ids") AND json_type("uncovered_behavior_ids")='array'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,testing_task_id),
  UNIQUE(testing_task_id),
  UNIQUE(verification_id),
  FOREIGN KEY("plan_version_id") REFERENCES "testing_plan_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_pack_version_id") REFERENCES "testing_pack_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("verification_id") REFERENCES "code_verifications"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("verification_id","testing_task_id") REFERENCES "code_verifications"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_pack_version_id","plan_version_id") REFERENCES "testing_pack_versions"("id","plan_version_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_findings" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "test_report_id" INTEGER NOT NULL CHECK("test_report_id" BETWEEN 1 AND 9007199254740991),
  "item_id" INTEGER CHECK("item_id" IS NULL OR ("item_id" BETWEEN 1 AND 9007199254740991)),
  "case_id" TEXT CHECK("case_id" IS NULL OR (length("case_id")>0)),
  "actual_behavior" TEXT NOT NULL CHECK(length("actual_behavior")>0),
  "expected_behavior" TEXT CHECK("expected_behavior" IS NULL OR (length("expected_behavior")>0)),
  "basis_ref" TEXT CHECK("basis_ref" IS NULL OR (json_valid("basis_ref") AND json_type("basis_ref")='object')),
  "classification" TEXT NOT NULL CHECK("classification" IN ('UNCLASSIFIED','PRODUCT','TEST_DESIGN','REQUIREMENT','ENVIRONMENT','UNKNOWN')),
  "state_version" INTEGER NOT NULL CHECK("state_version" BETWEEN 1 AND 9007199254740991),
  "review_reason" TEXT CHECK("review_reason" IS NULL OR (length("review_reason")>0)),
  "review_operation_id" INTEGER CHECK("review_operation_id" IS NULL OR ("review_operation_id" BETWEEN 1 AND 9007199254740991)),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "basis_document_id" INTEGER GENERATED ALWAYS AS (json_extract(basis_ref,'$.document_id')) STORED,
  "basis_revision_id" INTEGER GENERATED ALWAYS AS (json_extract(basis_ref,'$.revision_id')) STORED,
  CHECK((basis_ref IS NULL OR (json_type(basis_ref,'$.document_id')='integer' AND json_type(basis_ref,'$.revision_id')='integer' AND json_type(basis_ref,'$.quote')='text' AND length(json_extract(basis_ref,'$.quote'))>0)) IS TRUE),
  PRIMARY KEY("id"),
  FOREIGN KEY("item_id") REFERENCES "code_verification_items"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("review_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("test_report_id") REFERENCES "testing_reports"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("item_id","case_id") REFERENCES "code_verification_case_results"("item_id","case_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("basis_document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("basis_revision_id","basis_document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((case_id IS NULL OR item_id IS NOT NULL) IS TRUE)
) STRICT;

CREATE TABLE "testing_profile_versions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "name" TEXT NOT NULL CHECK(length("name")>0),
  "version" INTEGER NOT NULL CHECK("version" BETWEEN 1 AND 9007199254740991),
  "runner_refs" TEXT NOT NULL CHECK(json_valid("runner_refs") AND json_type("runner_refs")='array'),
  "environment_refs" TEXT NOT NULL CHECK(json_valid("environment_refs") AND json_type("environment_refs")='array'),
  "commands" TEXT NOT NULL CHECK(json_valid("commands") AND json_type("commands")='array'),
  "model_binding" TEXT CHECK("model_binding" IS NULL OR (json_valid("model_binding") AND json_type("model_binding")='object')),
  "limits" TEXT NOT NULL CHECK(json_valid("limits") AND json_type("limits")='object'),
  "admission_refs" TEXT NOT NULL CHECK(json_valid("admission_refs") AND json_type("admission_refs")='array'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(name,version)
) STRICT;

CREATE TABLE "testing_authorizations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "profile_version_id" INTEGER NOT NULL CHECK("profile_version_id" BETWEEN 1 AND 9007199254740991),
  "scope_kind" TEXT NOT NULL CHECK("scope_kind" IN ('TASK','PACK_VALIDATION')),
  "validation_id" INTEGER CHECK("validation_id" IS NULL OR ("validation_id" BETWEEN 1 AND 9007199254740991)),
  "status" TEXT NOT NULL CHECK("status" IN ('APPROVED_UNBOUND','EFFECTIVE','RETIRED')),
  "budget_limit_cny" TEXT NOT NULL CHECK(instr("budget_limit_cny",'.')=length("budget_limit_cny")-6 AND length("budget_limit_cny")>=8 AND "budget_limit_cny" NOT GLOB '*[^0-9.]*' AND substr("budget_limit_cny",-6) NOT GLOB '*[^0-9]*' AND instr(substr("budget_limit_cny",1,length("budget_limit_cny")-7),'.')=0 AND (substr("budget_limit_cny",1,1)<>'0' OR substr("budget_limit_cny",1,2)='0.')),
  "actor_ref" TEXT NOT NULL CHECK(length("actor_ref")>0),
  "approved_at" TEXT NOT NULL CHECK(length("approved_at")=24 AND "approved_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(id,testing_task_id),
  FOREIGN KEY("profile_version_id") REFERENCES "testing_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("validation_id") REFERENCES "testing_pack_validations"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_execution_profiles" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "name" TEXT NOT NULL CHECK(length("name")>0),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id")
) STRICT;

CREATE TABLE "code_check_sets" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "name" TEXT NOT NULL CHECK(length("name")>0),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id")
) STRICT;

CREATE TABLE "code_check_set_versions" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "check_set_id" INTEGER NOT NULL CHECK("check_set_id" BETWEEN 1 AND 9007199254740991),
  "version" INTEGER NOT NULL CHECK("version" BETWEEN 1 AND 9007199254740991),
  "owner_module" TEXT NOT NULL CHECK("owner_module" IN ('CODING','TESTING')),
  "protocol_version" TEXT NOT NULL CHECK("protocol_version"='CHECK20-CONTROL-1'),
  "items" TEXT NOT NULL CHECK(json_valid("items") AND json_type("items")='array'),
  "coverage_plan" TEXT NOT NULL CHECK(json_valid("coverage_plan") AND json_type("coverage_plan")='array'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(check_set_id,version),
  FOREIGN KEY("check_set_id") REFERENCES "code_check_sets"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_authorizations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "profile_version_id" INTEGER NOT NULL CHECK("profile_version_id" BETWEEN 1 AND 9007199254740991),
  "scope" TEXT NOT NULL CHECK(json_valid("scope") AND json_type("scope")='object'),
  "status" TEXT NOT NULL CHECK("status" IN ('APPROVED_UNBOUND','BOUND_PENDING_APPLY','EFFECTIVE','APPLY_FAILED','APPLY_UNKNOWN','RETIRED')),
  "approved_at" TEXT NOT NULL CHECK(length("approved_at")=24 AND "approved_at" GLOB '????-??-??T??:??:??.???Z'),
  "actor_ref" TEXT NOT NULL CHECK(length("actor_ref")>0),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_configuration_applications" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "old_profile_version_id" INTEGER CHECK("old_profile_version_id" IS NULL OR ("old_profile_version_id" BETWEEN 1 AND 9007199254740991)),
  "new_profile_version_id" INTEGER NOT NULL CHECK("new_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "authorization_id" INTEGER NOT NULL CHECK("authorization_id" BETWEEN 1 AND 9007199254740991),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "status" TEXT NOT NULL CHECK("status" IN ('PENDING','APPLYING','APPLIED','FAILED','UNKNOWN')),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  "applied_at" TEXT CHECK("applied_at" IS NULL OR (length("applied_at")=24 AND "applied_at" GLOB '????-??-??T??:??:??.???Z')),
  "effective_evidence" TEXT CHECK("effective_evidence" IS NULL OR (json_valid("effective_evidence") AND json_type("effective_evidence")='object')),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  FOREIGN KEY("authorization_id") REFERENCES "code_authorizations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("authorization_id","task_id") REFERENCES "code_authorizations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("new_profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("old_profile_version_id") REFERENCES "code_execution_profile_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_runtime_observations" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "task_id" INTEGER CHECK("task_id" IS NULL OR ("task_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "instance_id" INTEGER CHECK("instance_id" IS NULL OR ("instance_id" BETWEEN 1 AND 9007199254740991)),
  "command_id" INTEGER CHECK("command_id" IS NULL OR ("command_id" BETWEEN 1 AND 9007199254740991)),
  "operation_id" INTEGER NOT NULL CHECK("operation_id" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  "runtime_binding_ref" TEXT CHECK("runtime_binding_ref" IS NULL OR (length("runtime_binding_ref")>0)),
  "kind" TEXT NOT NULL CHECK("kind" IN ('PREPARE','QUIESCE','STOP','CLEANUP')),
  "result" TEXT NOT NULL CHECK("result" IN ('VERIFIED','UNAVAILABLE','UNKNOWN')),
  "reason_codes" TEXT NOT NULL CHECK(json_valid("reason_codes") AND json_type("reason_codes")='array'),
  "active_process_count" INTEGER CHECK("active_process_count" IS NULL OR ("active_process_count" BETWEEN 0 AND 9007199254740991)),
  "observed_at" TEXT NOT NULL CHECK(length("observed_at")=24 AND "observed_at" GLOB '????-??-??T??:??:??.???Z'),
  "evidence_ref" TEXT NOT NULL CHECK(length("evidence_ref")>0),
  PRIMARY KEY("id"),
  UNIQUE(id,task_id),
  UNIQUE(id,testing_task_id),
  CHECK((task_id IS NULL)<>(testing_task_id IS NULL)),
  FOREIGN KEY("command_id") REFERENCES "code_commands"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("command_id","task_id") REFERENCES "code_commands"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("command_id","testing_task_id") REFERENCES "code_commands"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id") REFERENCES "code_instances"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("instance_id","task_id") REFERENCES "code_instances"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","task_id") REFERENCES "code_operations"("id","task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("operation_id","testing_task_id") REFERENCES "code_operations"("id","testing_task_id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((result<>'VERIFIED' OR json_array_length(reason_codes)=0) IS TRUE),
  CHECK(((instance_id IS NOT NULL OR command_id IS NOT NULL) OR kind IN ('STOP','CLEANUP')) IS TRUE),
  CHECK((result<>'VERIFIED' OR kind NOT IN ('STOP','CLEANUP') OR active_process_count=0) IS TRUE)
) STRICT;

CREATE TABLE "code_delivery_repository_locks" (
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "delivery_id" INTEGER NOT NULL CHECK("delivery_id" BETWEEN 1 AND 9007199254740991),
  "control_generation" INTEGER NOT NULL CHECK("control_generation" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("repository_id"),
  FOREIGN KEY("delivery_id") REFERENCES "code_deliveries"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_task_materials" (
  "task_id" INTEGER NOT NULL CHECK("task_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "revision_id" INTEGER NOT NULL CHECK("revision_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("task_id","document_id"),
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("task_id") REFERENCES "code_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_repair_defects" (
  "repair_id" INTEGER NOT NULL CHECK("repair_id" BETWEEN 1 AND 9007199254740991),
  "defect_id" INTEGER NOT NULL CHECK("defect_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("repair_id","defect_id"),
  FOREIGN KEY("defect_id") REFERENCES "code_defects"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repair_id") REFERENCES "code_repairs"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_task_materials" (
  "testing_task_id" INTEGER NOT NULL CHECK("testing_task_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "revision_id" INTEGER NOT NULL CHECK("revision_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("testing_task_id","document_id"),
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_plan_materials" (
  "plan_version_id" INTEGER NOT NULL CHECK("plan_version_id" BETWEEN 1 AND 9007199254740991),
  "document_id" INTEGER NOT NULL CHECK("document_id" BETWEEN 1 AND 9007199254740991),
  "revision_id" INTEGER NOT NULL CHECK("revision_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("plan_version_id","document_id"),
  FOREIGN KEY("document_id") REFERENCES "requirement_documents"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("plan_version_id") REFERENCES "testing_plan_versions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id") REFERENCES "revisions"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("revision_id","document_id") REFERENCES "revisions"("id","document_id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "testing_validation_tasks" (
  "validation_id" INTEGER NOT NULL CHECK("validation_id" BETWEEN 1 AND 9007199254740991),
  "testing_task_id" INTEGER NOT NULL CHECK("testing_task_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("validation_id","testing_task_id"),
  FOREIGN KEY("testing_task_id") REFERENCES "testing_tasks"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("validation_id") REFERENCES "testing_pack_validations"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE "code_schema_state" (
  "singleton_id" INTEGER NOT NULL CHECK("singleton_id" BETWEEN 1 AND 9007199254740991),
  "schema_version" INTEGER NOT NULL CHECK("schema_version" BETWEEN 1 AND 9007199254740991),
  "schema_contract_sha256" TEXT NOT NULL CHECK(length("schema_contract_sha256")=64 AND "schema_contract_sha256" NOT GLOB '*[^0-9a-f]*'),
  "origin" TEXT NOT NULL CHECK("origin" IN ('FRESH_V20','UPGRADED_V151')),
  "upgrade_id" TEXT CHECK("upgrade_id" IS NULL OR (length("upgrade_id")>0)),
  "source_data_sha256" TEXT CHECK("source_data_sha256" IS NULL OR (length("source_data_sha256")=64 AND "source_data_sha256" NOT GLOB '*[^0-9a-f]*')),
  "committed_at" TEXT NOT NULL CHECK(length("committed_at")=24 AND "committed_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("singleton_id"),
  CHECK((singleton_id=1) IS TRUE),
  CHECK((schema_version=200) IS TRUE),
  CHECK(((origin='FRESH_V20' AND upgrade_id IS NULL AND source_data_sha256 IS NULL) OR (origin='UPGRADED_V151' AND upgrade_id IS NOT NULL AND source_data_sha256 IS NOT NULL)) IS TRUE)
) STRICT;

CREATE TABLE "code_defect_evidence_refs" (
  "defect_id" INTEGER NOT NULL CHECK("defect_id" BETWEEN 1 AND 9007199254740991),
  "ordinal" INTEGER NOT NULL CHECK("ordinal" BETWEEN 1 AND 9007199254740991),
  "kind" TEXT NOT NULL CHECK("kind" IN ('VERIFICATION_ITEM','QUESTION','OPERATION','COMMAND','LLM_USE')),
  "source_id" INTEGER NOT NULL CHECK("source_id" BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY("defect_id","ordinal"),
  FOREIGN KEY("defect_id") REFERENCES "code_defects"("id") DEFERRABLE INITIALLY DEFERRED
) STRICT;

DROP TRIGGER "llm_uses_immutable_fields";
DROP TRIGGER "idempotency_success_status_insert";
DROP TRIGGER "idempotency_success_status_update";
DROP TRIGGER "idempotency_success_immutable";
DROP TRIGGER "idempotency_success_retained";
DROP TRIGGER "idempotency_identity_immutable";
CREATE TABLE "llm_uses_v200" (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  guide_run_id INTEGER CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  call_no INTEGER NOT NULL CHECK (call_no BETWEEN 1 AND 9007199254740991),
  attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 9007199254740991),
  provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_version TEXT,
  function_type TEXT NOT NULL,
  prompt_config TEXT NOT NULL,
  request_snapshot_json TEXT NOT NULL CHECK (json_valid(request_snapshot_json) AND json_type(request_snapshot_json)='object'),
  parsed_output_json TEXT CHECK (json_valid(parsed_output_json) AND json_type(parsed_output_json)='object' OR parsed_output_json IS NULL),
  trusted_output_json TEXT CHECK (json_valid(trusted_output_json) AND json_type(trusted_output_json)='object' OR trusted_output_json IS NULL),
  input_summary TEXT NOT NULL,
  context_manifest_json TEXT NOT NULL CHECK (json_valid(context_manifest_json) AND json_type(context_manifest_json)='object'),
  raw_response_json TEXT CHECK (json_valid(raw_response_json) AND json_type(raw_response_json)='object' OR raw_response_json IS NULL),
  finish_reason TEXT,
  parse_status TEXT NOT NULL,
  parse_error TEXT,
  validation_status TEXT NOT NULL,
  validation_error TEXT,
  call_status TEXT NOT NULL,
  input_tokens INTEGER CHECK (input_tokens BETWEEN 0 AND 9007199254740991),
  output_tokens INTEGER CHECK (output_tokens BETWEEN 0 AND 9007199254740991),
  cache_info_json TEXT CHECK (json_valid(cache_info_json) AND json_type(cache_info_json)='object' OR cache_info_json IS NULL),
  provider_request_id TEXT,
  started_at TEXT NOT NULL CHECK (length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  ended_at TEXT CHECK (length(ended_at)=24 AND ended_at GLOB '????-??-??T??:??:??.???Z'),
  duration_ms INTEGER CHECK (duration_ms BETWEEN 0 AND 9007199254740991),
  error_code TEXT,
  error_message TEXT,
  cost TEXT,
  cost_currency TEXT,
  "execution_session_id" INTEGER CHECK("execution_session_id" IS NULL OR ("execution_session_id" BETWEEN 1 AND 9007199254740991)),
  "testing_task_id" INTEGER CHECK("testing_task_id" IS NULL OR ("testing_task_id" BETWEEN 1 AND 9007199254740991)),
  "operation_id" INTEGER CHECK("operation_id" IS NULL OR ("operation_id" BETWEEN 1 AND 9007199254740991)),
  "gateway_request_id" TEXT CHECK("gateway_request_id" IS NULL OR (length("gateway_request_id")>0)),
  "retry_of_llm_use_id" INTEGER CHECK("retry_of_llm_use_id" IS NULL OR ("retry_of_llm_use_id" BETWEEN 1 AND 9007199254740991)),
  "protocol_version" TEXT CHECK("protocol_version" IS NULL OR (length("protocol_version")>0)),
  "call_purpose" TEXT CHECK("call_purpose" IS NULL OR ("call_purpose" IN ('CODE','COMPACTION','TEST_DESIGN'))),
  "transport_status" TEXT CHECK("transport_status" IS NULL OR ("transport_status" IN ('NOT_SENT','SENDING','SENT','COMPLETE','INTERRUPTED','UNKNOWN'))),
  "usage_status" TEXT CHECK("usage_status" IS NULL OR ("usage_status" IN ('NOT_REPORTED','PARTIAL','FINAL','DISPUTED'))),
  "capture_status" TEXT CHECK("capture_status" IS NULL OR ("capture_status" IN ('FULL','REDACTED','INCOMPLETE'))),
  "source_evidence_ref" TEXT CHECK("source_evidence_ref" IS NULL OR (length("source_evidence_ref")>0)),
  CHECK(attempt_no=1 AND (guide_run_id IS NULL OR call_no=1)),
  CHECK ((validation_status='SUCCEEDED' AND trusted_output_json IS NOT NULL) OR (validation_status<>'SUCCEEDED' AND trusted_output_json IS NULL)),
  UNIQUE (guide_run_id, call_no, attempt_no),
  FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id),
  CHECK (provider_request_id IS NULL OR length(provider_request_id)<=1024),
  CHECK ((cost IS NULL AND cost_currency IS NULL) OR (cost IS NOT NULL AND cost_currency IS NOT NULL)),
  UNIQUE(id,testing_task_id),
  UNIQUE(id,execution_session_id),
  CHECK(((guide_run_id IS NOT NULL)+(execution_session_id IS NOT NULL)+(testing_task_id IS NOT NULL))=1),
  FOREIGN KEY(execution_session_id) REFERENCES code_sessions(id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(testing_task_id) REFERENCES testing_tasks(id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(operation_id) REFERENCES code_operations(id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(retry_of_llm_use_id) REFERENCES llm_uses(id) DEFERRABLE INITIALLY DEFERRED,
  CHECK(((guide_run_id IS NOT NULL AND execution_session_id IS NULL AND testing_task_id IS NULL
          AND operation_id IS NULL AND gateway_request_id IS NULL AND protocol_version IS NULL
          AND call_purpose IS NULL AND transport_status IS NULL AND usage_status IS NULL
          AND capture_status IS NULL AND source_evidence_ref IS NULL AND retry_of_llm_use_id IS NULL)
        OR (guide_run_id IS NULL AND operation_id IS NOT NULL AND source_evidence_ref IS NOT NULL
          AND transport_status IS NOT NULL AND usage_status IS NOT NULL AND capture_status IS NOT NULL
          AND (provider_request_id IS NULL OR length(provider_request_id) BETWEEN 1 AND 1024)
          AND ((execution_session_id IS NOT NULL AND testing_task_id IS NULL
            AND function_type='CODE_EXECUTION' AND protocol_version='OC20-MODEL-1'
            AND gateway_request_id IS NOT NULL AND call_purpose IN ('CODE','COMPACTION')
            AND parse_status='NOT_APPLICABLE' AND validation_status='NOT_APPLICABLE'
            AND parsed_output_json IS NULL AND trusted_output_json IS NULL)
          OR (testing_task_id IS NOT NULL AND execution_session_id IS NULL
            AND function_type='TEST_PLAN_DRAFT' AND protocol_version='TEST20-PLAN-1'
            AND gateway_request_id IS NULL AND call_purpose='TEST_DESIGN'
            AND parse_status IN ('PENDING','SUCCEEDED','FAILED')
            AND validation_status IN ('PENDING','SUCCEEDED','FAILED')
            AND retry_of_llm_use_id IS NULL)))) IS TRUE)
) STRICT;
INSERT INTO "llm_uses_v200"("id","guide_run_id","call_no","attempt_no","provider","model_name","model_version","function_type","prompt_config","request_snapshot_json","parsed_output_json","trusted_output_json","input_summary","context_manifest_json","raw_response_json","finish_reason","parse_status","parse_error","validation_status","validation_error","call_status","input_tokens","output_tokens","cache_info_json","provider_request_id","started_at","ended_at","duration_ms","error_code","error_message","cost","cost_currency") SELECT "id","guide_run_id","call_no","attempt_no","provider","model_name","model_version","function_type","prompt_config","request_snapshot_json","parsed_output_json","trusted_output_json","input_summary","context_manifest_json","raw_response_json","finish_reason","parse_status","parse_error","validation_status","validation_error","call_status","input_tokens","output_tokens","cache_info_json","provider_request_id","started_at","ended_at","duration_ms","error_code","error_message","cost","cost_currency" FROM "llm_uses";
DROP TABLE "llm_uses";
ALTER TABLE "llm_uses_v200" RENAME TO "llm_uses";
CREATE TABLE "idempotency_records_v200" (
  capability_id TEXT NOT NULL,
  target_identity TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  business_input_json TEXT CHECK(business_input_json IS NULL OR (json_valid(business_input_json) AND json_type(business_input_json)='object')),
  status TEXT NOT NULL CHECK(status IN ('PROCESSING','SUCCEEDED','REJECTED','CLOSED')),
  owner_epoch TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  success_result_json TEXT CHECK(success_result_json IS NULL OR (json_valid(success_result_json) AND json_type(success_result_json)='object')),
  http_status INTEGER,
  error_result_json TEXT CHECK(error_result_json IS NULL OR (json_valid(error_result_json) AND json_type(error_result_json)='object')),
  PRIMARY KEY(capability_id,target_identity,idempotency_key),
  CHECK((
       (status='PROCESSING' AND business_input_json IS NOT NULL AND success_result_json IS NULL
          AND error_result_json IS NULL AND http_status IS NULL)
    OR (status='SUCCEEDED' AND business_input_json IS NOT NULL AND success_result_json IS NOT NULL
          AND error_result_json IS NULL AND http_status BETWEEN 200 AND 299)
    OR (status='REJECTED' AND capability_id IN ('APP-CODE-CMD-C01','APP-CODE-CMD-C02','APP-CODE-CMD-C05','APP-CODE-CMD-C07','APP-CODE-CMD-C08','APP-CODE-CMD-C09','APP-CODE-CMD-C10','APP-CODE-CMD-C15','APP-CODE-CMD-C32','APP-CODE-CMD-C35','APP-CODE-CMD-C36','APP-CODE-CMD-C37','APP-CODE-CMD-C38','APP-CODE-CMD-C39','APP-CODE-CMD-C40','APP-CODE-CMD-C46','APP-CODE-CMD-C47','APP-CODE-CMD-C48','APP-CODE-CMD-C49','APP-CODE-CMD-C50','APP-CODE-CMD-C51','APP-CODE-CMD-C58','APP-CODE-CMD-C59','APP-CODE-CMD-C62','APP-CODE-CMD-C64','APP-CODE-CMD-C68','APP-CODE-CMD-C69','APP-TEST-CMD-C01','APP-TEST-CMD-C04','APP-TEST-CMD-C06','APP-TEST-CMD-C09','APP-TEST-CMD-C12','APP-TEST-CMD-C13','APP-TEST-CMD-C14','APP-TEST-CMD-C15','APP-TEST-CMD-C18','APP-TEST-CMD-C19','APP-TEST-CMD-C21','APP-TEST-CMD-C22','APP-TEST-CMD-C23','APP-TEST-CMD-C26','APP-TEST-CMD-C27','APP-TEST-CMD-C28','APP-TEST-CMD-C29','APP-TEST-CMD-C30','APP-TEST-CMD-C31','APP-TEST-CMD-C32','APP-TEST-CMD-C40')
          AND business_input_json IS NOT NULL AND success_result_json IS NULL AND error_result_json IS NOT NULL
          AND json_type(error_result_json,'$.data')='null'
          AND json_type(error_result_json,'$.code')='text'
          AND json_extract(error_result_json,'$.code')<>'COMMAND_CLOSED'
          AND http_status BETWEEN 400 AND 499 AND CASE json_extract(error_result_json,'$.code')
          WHEN 'INVALID_INPUT' THEN 422 WHEN 'CHECK_CONFIGURATION_INVALID' THEN 422 WHEN 'BASIS_REF_INVALID' THEN 422 WHEN 'DEFECT_SOURCE_MISMATCH' THEN 422 WHEN 'BUDGET_NOT_INCREASED' THEN 422 WHEN 'NOT_FOUND' THEN 404 WHEN 'AUTHORIZATION_NOT_APPLICABLE' THEN 403 WHEN 'PERMISSION_NOT_GRANTED' THEN 403 WHEN 'DELIVERY_NOT_AUTHORIZED' THEN 403 WHEN 'COMMAND_CLOSED' THEN 409 WHEN 'VERSION_CONFLICT' THEN 409 WHEN 'ACTIVE_TASK_EXISTS' THEN 409 WHEN 'INVALID_STATE' THEN 409 WHEN 'TASK_ENDED' THEN 409 WHEN 'OPERATION_CONFLICT' THEN 409 WHEN 'OPERATION_IN_PROGRESS' THEN 409 WHEN 'RESOURCE_CONFLICT' THEN 409 WHEN 'TEST_REPORT_NOT_ELIGIBLE' THEN 409 WHEN 'TEST_SOURCE_MISMATCH' THEN 409 WHEN 'TEST_ASSET_REVOKED' THEN 409 WHEN 'VERIFICATION_STAGE_NOT_READY' THEN 409 WHEN 'SOURCE_CHANGED' THEN 409 WHEN 'SOURCE_BUSY' THEN 409 WHEN 'SOURCE_UNSUPPORTED' THEN 409 WHEN 'PRECONDITION_FAILED' THEN 409 WHEN 'BASIS_NOT_CONFIRMED' THEN 409 WHEN 'EXTERNAL_RESULT_UNKNOWN' THEN 409 WHEN 'EXECUTION_NOT_STOPPED' THEN 409 WHEN 'QUESTION_NOT_OPEN' THEN 409 WHEN 'SESSION_NOT_CURRENT' THEN 409 WHEN 'WRITER_ACTIVE' THEN 409 WHEN 'CONTENT_NOT_READY' THEN 409 WHEN 'CANDIDATE_NOT_CURRENT' THEN 409 WHEN 'CHECKS_NOT_PASSED' THEN 409 WHEN 'HANDOFF_CHECKS_NOT_PASSED' THEN 409 WHEN 'DELIVERY_PLAN_STALE' THEN 409 WHEN 'TARGET_CHANGED' THEN 409 WHEN 'TARGET_CHECKED_OUT' THEN 409 WHEN 'DELIVERY_WINDOW_REQUIRED' THEN 409 WHEN 'REPOSITORY_UNSUPPORTED' THEN 409 END=http_status)
    OR (status='CLOSED' AND capability_id IN ('APP-CODE-CMD-C01','APP-CODE-CMD-C02','APP-CODE-CMD-C05','APP-CODE-CMD-C07','APP-CODE-CMD-C08','APP-CODE-CMD-C09','APP-CODE-CMD-C10','APP-CODE-CMD-C15','APP-CODE-CMD-C32','APP-CODE-CMD-C35','APP-CODE-CMD-C36','APP-CODE-CMD-C37','APP-CODE-CMD-C38','APP-CODE-CMD-C39','APP-CODE-CMD-C40','APP-CODE-CMD-C46','APP-CODE-CMD-C47','APP-CODE-CMD-C48','APP-CODE-CMD-C49','APP-CODE-CMD-C50','APP-CODE-CMD-C51','APP-CODE-CMD-C58','APP-CODE-CMD-C59','APP-CODE-CMD-C62','APP-CODE-CMD-C64','APP-CODE-CMD-C68','APP-CODE-CMD-C69','APP-TEST-CMD-C01','APP-TEST-CMD-C04','APP-TEST-CMD-C06','APP-TEST-CMD-C09','APP-TEST-CMD-C12','APP-TEST-CMD-C13','APP-TEST-CMD-C14','APP-TEST-CMD-C15','APP-TEST-CMD-C18','APP-TEST-CMD-C19','APP-TEST-CMD-C21','APP-TEST-CMD-C22','APP-TEST-CMD-C23','APP-TEST-CMD-C26','APP-TEST-CMD-C27','APP-TEST-CMD-C28','APP-TEST-CMD-C29','APP-TEST-CMD-C30','APP-TEST-CMD-C31','APP-TEST-CMD-C32','APP-TEST-CMD-C40')
          AND business_input_json IS NULL AND success_result_json IS NULL AND error_result_json IS NOT NULL
          AND http_status=409 AND json_extract(error_result_json,'$.code')='COMMAND_CLOSED'
          AND json_type(error_result_json,'$.data')='null'
          AND json_extract(error_result_json,'$.details.method')='POST'
          AND target_identity='POST '||json_extract(error_result_json,'$.details.path')
          AND json_extract(error_result_json,'$.details.closed_at')=created_at AND updated_at=created_at)
    ) IS TRUE)
) STRICT;
INSERT INTO "idempotency_records_v200"("capability_id","target_identity","idempotency_key","business_input_json","status","owner_epoch","created_at","updated_at","success_result_json","http_status") SELECT "capability_id","target_identity","idempotency_key","business_input_json","status","owner_epoch","created_at","updated_at","success_result_json","http_status" FROM "idempotency_records";
DROP TABLE "idempotency_records";
ALTER TABLE "idempotency_records_v200" RENAME TO "idempotency_records";

CREATE TRIGGER llm_uses_immutable_fields BEFORE UPDATE ON llm_uses
WHEN NEW.id IS NOT OLD.id OR NEW.guide_run_id IS NOT OLD.guide_run_id OR NEW.function_type IS NOT OLD.function_type
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;


CREATE TRIGGER idempotency_success_status_insert BEFORE INSERT ON idempotency_records
WHEN NEW.status='SUCCEEDED' AND NEW.http_status IS NULL
BEGIN SELECT RAISE(ABORT, 'SUCCESS_HTTP_STATUS_REQUIRED'); END;


CREATE TRIGGER idempotency_success_status_update BEFORE UPDATE ON idempotency_records
WHEN NEW.status='SUCCEEDED' AND NEW.http_status IS NULL
BEGIN SELECT RAISE(ABORT, 'SUCCESS_HTTP_STATUS_REQUIRED'); END;


CREATE TRIGGER idempotency_success_immutable BEFORE UPDATE ON idempotency_records
WHEN OLD.status='SUCCEEDED'
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_SUCCESS'); END;


CREATE TRIGGER idempotency_success_retained BEFORE DELETE ON idempotency_records
WHEN OLD.status='SUCCEEDED'
BEGIN SELECT RAISE(ABORT, 'SUCCESS_MUST_BE_RETAINED'); END;


CREATE TRIGGER idempotency_identity_immutable BEFORE UPDATE ON idempotency_records
WHEN NEW.capability_id IS NOT OLD.capability_id OR NEW.target_identity IS NOT OLD.target_identity OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.business_input_json IS NOT OLD.business_input_json OR NEW.owner_epoch IS NOT OLD.owner_epoch OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CLAIM_IDENTITY'); END;

CREATE UNIQUE INDEX code_repository_registration_one_reserved_id ON code_operations(resource_id) WHERE resource_kind='REPOSITORY' AND operation_type='REGISTER_REPOSITORY';
CREATE UNIQUE INDEX code_repository_observation_one_operation ON code_repository_observations(operation_id);
CREATE UNIQUE INDEX code_tasks_one_active_document ON code_tasks(document_id) WHERE status NOT IN ('COMPLETED','TERMINATED');
CREATE UNIQUE INDEX code_operations_one_code_stop ON code_operations(task_id) WHERE operation_type='TERMINATE' AND task_id IS NOT NULL;
CREATE UNIQUE INDEX code_operations_one_test_stop ON code_operations(testing_task_id) WHERE operation_type='TERMINATE' AND testing_task_id IS NOT NULL;
CREATE UNIQUE INDEX code_waiting_one_code_source ON code_waiting_items(task_id,kind,source_kind,source_id) WHERE status='OPEN' AND task_id IS NOT NULL;
CREATE UNIQUE INDEX code_waiting_one_test_source ON code_waiting_items(testing_task_id,kind,source_kind,source_id) WHERE status='OPEN' AND testing_task_id IS NOT NULL;
CREATE UNIQUE INDEX code_sessions_one_writer ON code_sessions(task_id,control_generation) WHERE status IN ('PREPARING','ACTIVE','QUIESCING','UNKNOWN');
CREATE UNIQUE INDEX code_defects_one_testing_source ON code_defects(task_id,testing_finding_id) WHERE testing_finding_id IS NOT NULL;
CREATE UNIQUE INDEX llm_one_gateway_request ON llm_uses(gateway_request_id) WHERE gateway_request_id IS NOT NULL;
CREATE UNIQUE INDEX llm_one_code_call ON llm_uses(execution_session_id,call_no) WHERE execution_session_id IS NOT NULL;
CREATE UNIQUE INDEX llm_one_testing_call ON llm_uses(testing_task_id,call_no) WHERE testing_task_id IS NOT NULL;
CREATE TRIGGER "code_tasks_identity_fixed" BEFORE UPDATE ON "code_tasks"
WHEN NEW."base_snapshot_id" IS NOT OLD."base_snapshot_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."id" IS NOT OLD."id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."target_branch" IS NOT OLD."target_branch"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_tasks_history_retained" BEFORE DELETE ON "code_tasks"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_snapshots_identity_fixed" BEFORE UPDATE ON "code_snapshots"
WHEN NEW."commit_oid" IS NOT OLD."commit_oid" OR NEW."content_policy_version" IS NOT OLD."content_policy_version" OR NEW."content_profile_version_id" IS NOT OLD."content_profile_version_id" OR NEW."content_tree_oid" IS NOT OLD."content_tree_oid" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."registered_at" IS NOT OLD."registered_at" OR NEW."registration_operation_id" IS NOT OLD."registration_operation_id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."retention_ref" IS NOT OLD."retention_ref"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_snapshots_history_retained" BEFORE DELETE ON "code_snapshots"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_candidates_identity_fixed" BEFORE UPDATE ON "code_candidates"
WHEN NEW."base_snapshot_id" IS NOT OLD."base_snapshot_id" OR NEW."byte_count" IS NOT OLD."byte_count" OR NEW."capture_operation_id" IS NOT OLD."capture_operation_id" OR NEW."captured_at" IS NOT OLD."captured_at" OR NEW."content_policy_version" IS NOT OLD."content_policy_version" OR NEW."content_store_key" IS NOT OLD."content_store_key" OR NEW."content_tree_oid" IS NOT OLD."content_tree_oid" OR NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."file_count" IS NOT OLD."file_count" OR NEW."id" IS NOT OLD."id" OR NEW."manifest_sha256" IS NOT OLD."manifest_sha256" OR NEW."parent_candidate_id" IS NOT OLD."parent_candidate_id" OR NEW."role" IS NOT OLD."role" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_candidates_history_retained" BEFORE DELETE ON "code_candidates"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_candidates_published_for_testing_at_fixed" BEFORE UPDATE ON "code_candidates"
WHEN OLD."published_for_testing_at" IS NOT NULL AND NEW."published_for_testing_at" IS NOT OLD."published_for_testing_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_candidates_publication_operation_id_fixed" BEFORE UPDATE ON "code_candidates"
WHEN OLD."publication_operation_id" IS NOT NULL AND NEW."publication_operation_id" IS NOT OLD."publication_operation_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_defects_identity_fixed" BEFORE UPDATE ON "code_defects"
WHEN NEW."actor_ref" IS NOT OLD."actor_ref" OR NEW."actual_behavior" IS NOT OLD."actual_behavior" OR NEW."basis_ref" IS NOT OLD."basis_ref" OR NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."expected_behavior" IS NOT OLD."expected_behavior" OR NEW."id" IS NOT OLD."id" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_finding_id" IS NOT OLD."testing_finding_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_defects_history_retained" BEFORE DELETE ON "code_defects"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_repairs_identity_fixed" BEFORE UPDATE ON "code_repairs"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."source_candidate_id" IS NOT OLD."source_candidate_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_repairs_history_retained" BEFORE DELETE ON "code_repairs"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_delivery_plans_identity_fixed" BEFORE UPDATE ON "code_delivery_plans"
WHEN NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."expected_target_commit" IS NOT OLD."expected_target_commit" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."result_tree_oid" IS NOT OLD."result_tree_oid" OR NEW."target_branch" IS NOT OLD."target_branch" OR NEW."target_content_store_key" IS NOT OLD."target_content_store_key" OR NEW."target_manifest_sha256" IS NOT OLD."target_manifest_sha256" OR NEW."target_tree_oid" IS NOT OLD."target_tree_oid" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."test_report_id" IS NOT OLD."test_report_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_delivery_plans_history_retained" BEFORE DELETE ON "code_delivery_plans"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_acceptances_identity_fixed" BEFORE UPDATE ON "code_acceptances"
WHEN NEW."accepted_at" IS NOT OLD."accepted_at" OR NEW."actor_ref" IS NOT OLD."actor_ref" OR NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."delivery_plan_id" IS NOT OLD."delivery_plan_id" OR NEW."id" IS NOT OLD."id" OR NEW."manual_risk_accepted" IS NOT OLD."manual_risk_accepted" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."test_report_id" IS NOT OLD."test_report_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_acceptances_history_retained" BEFORE DELETE ON "code_acceptances"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_deliveries_identity_fixed" BEFORE UPDATE ON "code_deliveries"
WHEN NEW."acceptance_id" IS NOT OLD."acceptance_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."delivery_plan_id" IS NOT OLD."delivery_plan_id" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_deliveries_history_retained" BEFORE DELETE ON "code_deliveries"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_deliveries_commit_input_ref_fixed" BEFORE UPDATE ON "code_deliveries"
WHEN OLD."commit_input_ref" IS NOT NULL AND NEW."commit_input_ref" IS NOT OLD."commit_input_ref"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_deliveries_commit_input_sha256_fixed" BEFORE UPDATE ON "code_deliveries"
WHEN OLD."commit_input_sha256" IS NOT NULL AND NEW."commit_input_sha256" IS NOT OLD."commit_input_sha256"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_deliveries_planned_commit_oid_fixed" BEFORE UPDATE ON "code_deliveries"
WHEN OLD."planned_commit_oid" IS NOT NULL AND NEW."planned_commit_oid" IS NOT OLD."planned_commit_oid"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_deliveries_delivered_at_fixed" BEFORE UPDATE ON "code_deliveries"
WHEN OLD."delivered_at" IS NOT NULL AND NEW."delivered_at" IS NOT OLD."delivered_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_delivery_windows_identity_fixed" BEFORE UPDATE ON "code_delivery_windows"
WHEN NEW."confirmed_at" IS NOT OLD."confirmed_at" OR NEW."controller_epoch_ref" IS NOT OLD."controller_epoch_ref" OR NEW."delivery_id" IS NOT OLD."delivery_id" OR NEW."expires_at" IS NOT OLD."expires_at" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_delivery_windows_history_retained" BEFORE DELETE ON "code_delivery_windows"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_workspaces_identity_fixed" BEFORE UPDATE ON "code_workspaces"
WHEN NEW."base_snapshot_id" IS NOT OLD."base_snapshot_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."private_location_key" IS NOT OLD."private_location_key" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_workspaces_history_retained" BEFORE DELETE ON "code_workspaces"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_workspaces_ready_at_fixed" BEFORE UPDATE ON "code_workspaces"
WHEN OLD."ready_at" IS NOT NULL AND NEW."ready_at" IS NOT OLD."ready_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_identity_fixed" BEFORE UPDATE ON "code_instances"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."effective_profile_version_id" IS NOT OLD."effective_profile_version_id" OR NEW."executor_version" IS NOT OLD."executor_version" OR NEW."id" IS NOT OLD."id" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."workspace_id" IS NOT OLD."workspace_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_instances_history_retained" BEFORE DELETE ON "code_instances"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_instances_process_identity_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."process_identity" IS NOT NULL AND NEW."process_identity" IS NOT OLD."process_identity"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_runtime_binding_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."runtime_binding" IS NOT NULL AND NEW."runtime_binding" IS NOT OLD."runtime_binding"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_connection_ref_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."connection_ref" IS NOT NULL AND NEW."connection_ref" IS NOT OLD."connection_ref"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_native_storage_ref_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."native_storage_ref" IS NOT NULL AND NEW."native_storage_ref" IS NOT OLD."native_storage_ref"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_ready_at_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."ready_at" IS NOT NULL AND NEW."ready_at" IS NOT OLD."ready_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_instances_stopped_at_fixed" BEFORE UPDATE ON "code_instances"
WHEN OLD."stopped_at" IS NOT NULL AND NEW."stopped_at" IS NOT OLD."stopped_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_sessions_identity_fixed" BEFORE UPDATE ON "code_sessions"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."instance_id" IS NOT OLD."instance_id" OR NEW."role" IS NOT OLD."role" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_sessions_history_retained" BEFORE DELETE ON "code_sessions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_sessions_native_session_id_fixed" BEFORE UPDATE ON "code_sessions"
WHEN OLD."native_session_id" IS NOT NULL AND NEW."native_session_id" IS NOT OLD."native_session_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_sessions_gateway_credential_ref_fixed" BEFORE UPDATE ON "code_sessions"
WHEN OLD."gateway_credential_ref" IS NOT NULL AND NEW."gateway_credential_ref" IS NOT OLD."gateway_credential_ref"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_commands_identity_fixed" BEFORE UPDATE ON "code_commands"
WHEN NEW."command_ref" IS NOT OLD."command_ref" OR NEW."config_version_id" IS NOT OLD."config_version_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."purpose" IS NOT OLD."purpose" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_profile_version_id" IS NOT OLD."testing_profile_version_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_commands_history_retained" BEFORE DELETE ON "code_commands"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_commands_process_identity_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD."process_identity" IS NOT NULL AND NEW."process_identity" IS NOT OLD."process_identity"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_commands_runtime_binding_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD."runtime_binding" IS NOT NULL AND NEW."runtime_binding" IS NOT OLD."runtime_binding"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_commands_started_at_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD."started_at" IS NOT NULL AND NEW."started_at" IS NOT OLD."started_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_commands_ended_at_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD."ended_at" IS NOT NULL AND NEW."ended_at" IS NOT OLD."ended_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_commands_exit_code_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD."exit_code" IS NOT NULL AND NEW."exit_code" IS NOT OLD."exit_code"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_execution_records_identity_fixed" BEFORE UPDATE ON "code_execution_records"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."id" IS NOT OLD."id" OR NEW."instance_id" IS NOT OLD."instance_id" OR NEW."kind" IS NOT OLD."kind" OR NEW."native_event_id" IS NOT OLD."native_event_id" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."session_id" IS NOT OLD."session_id" OR NEW."source_id" IS NOT OLD."source_id" OR NEW."source_kind" IS NOT OLD."source_kind" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."text" IS NOT OLD."text"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_execution_records_history_retained" BEFORE DELETE ON "code_execution_records"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_operations_identity_fixed" BEFORE UPDATE ON "code_operations"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."expected_state_version" IS NOT OLD."expected_state_version" OR NEW."fixed_input" IS NOT OLD."fixed_input" OR NEW."id" IS NOT OLD."id" OR NEW."idempotency_key" IS NOT OLD."idempotency_key" OR NEW."operation_type" IS NOT OLD."operation_type" OR NEW."resource_id" IS NOT OLD."resource_id" OR NEW."resource_kind" IS NOT OLD."resource_kind" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_operations_history_retained" BEFORE DELETE ON "code_operations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_operation_steps_identity_fixed" BEFORE UPDATE ON "code_operation_steps"
WHEN NEW."fixed_input" IS NOT OLD."fixed_input" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."step_no" IS NOT OLD."step_no" OR NEW."step_type" IS NOT OLD."step_type"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_operation_steps_history_retained" BEFORE DELETE ON "code_operation_steps"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_operation_steps_external_identity_fixed" BEFORE UPDATE ON "code_operation_steps"
WHEN OLD."external_identity" IS NOT NULL AND NEW."external_identity" IS NOT OLD."external_identity"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_operation_steps_result_ref_fixed" BEFORE UPDATE ON "code_operation_steps"
WHEN OLD."result_ref" IS NOT NULL AND NEW."result_ref" IS NOT OLD."result_ref"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_waiting_items_identity_fixed" BEFORE UPDATE ON "code_waiting_items"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."kind" IS NOT OLD."kind" OR NEW."resume_phase" IS NOT OLD."resume_phase" OR NEW."source_id" IS NOT OLD."source_id" OR NEW."source_kind" IS NOT OLD."source_kind" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_waiting_items_history_retained" BEFORE DELETE ON "code_waiting_items"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_execution_profile_versions_identity_fixed" BEFORE UPDATE ON "code_execution_profile_versions"
WHEN NEW."capability_evidence_refs" IS NOT OLD."capability_evidence_refs" OR NEW."capture_rules" IS NOT OLD."capture_rules" OR NEW."check_set_version_id" IS NOT OLD."check_set_version_id" OR NEW."commands" IS NOT OLD."commands" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."delivery" IS NOT OLD."delivery" OR NEW."environment" IS NOT OLD."environment" OR NEW."executor" IS NOT OLD."executor" OR NEW."git" IS NOT OLD."git" OR NEW."id" IS NOT OLD."id" OR NEW."limits" IS NOT OLD."limits" OR NEW."models" IS NOT OLD."models" OR NEW."profile_id" IS NOT OLD."profile_id" OR NEW."version" IS NOT OLD."version"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_execution_profile_versions_history_retained" BEFORE DELETE ON "code_execution_profile_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_verifications_identity_fixed" BEFORE UPDATE ON "code_verifications"
WHEN NEW."backend_handoff_operation_id" IS NOT OLD."backend_handoff_operation_id" OR NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."check_set_version_id" IS NOT OLD."check_set_version_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."environment_record_id" IS NOT OLD."environment_record_id" OR NEW."frontend_handoff_operation_id" IS NOT OLD."frontend_handoff_operation_id" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."owner_kind" IS NOT OLD."owner_kind" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."purpose" IS NOT OLD."purpose" OR NEW."role" IS NOT OLD."role" OR NEW."scope_stages" IS NOT OLD."scope_stages" OR NEW."selected_check_ids" IS NOT OLD."selected_check_ids" OR NEW."snapshot_id" IS NOT OLD."snapshot_id" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_profile_version_id" IS NOT OLD."testing_profile_version_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_verifications_history_retained" BEFORE DELETE ON "code_verifications"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_verification_items_identity_fixed" BEFORE UPDATE ON "code_verification_items"
WHEN NEW."check_id" IS NOT OLD."check_id" OR NEW."check_kind" IS NOT OLD."check_kind" OR NEW."evidence_kind" IS NOT OLD."evidence_kind" OR NEW."id" IS NOT OLD."id" OR NEW."required" IS NOT OLD."required" OR NEW."verification_id" IS NOT OLD."verification_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_verification_items_history_retained" BEFORE DELETE ON "code_verification_items"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_verification_case_results_identity_fixed" BEFORE UPDATE ON "code_verification_case_results"
WHEN NEW."assertion_results" IS NOT OLD."assertion_results" OR NEW."capture_status" IS NOT OLD."capture_status" OR NEW."case_id" IS NOT OLD."case_id" OR NEW."item_id" IS NOT OLD."item_id" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."result" IS NOT OLD."result"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_verification_case_results_history_retained" BEFORE DELETE ON "code_verification_case_results"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_environment_records_identity_fixed" BEFORE UPDATE ON "code_environment_records"
WHEN NEW."check_resource_refs" IS NOT OLD."check_resource_refs" OR NEW."dependency_refs" IS NOT OLD."dependency_refs" OR NEW."effective_config_application_id" IS NOT OLD."effective_config_application_id" OR NEW."id" IS NOT OLD."id" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."runner_refs" IS NOT OLD."runner_refs" OR NEW."runtime_refs" IS NOT OLD."runtime_refs" OR NEW."scope_key" IS NOT OLD."scope_key" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_profile_version_id" IS NOT OLD."testing_profile_version_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_environment_records_history_retained" BEFORE DELETE ON "code_environment_records"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_model_response_frames_identity_fixed" BEFORE UPDATE ON "code_model_response_frames"
WHEN NEW."capture_status" IS NOT OLD."capture_status" OR NEW."frame_json" IS NOT OLD."frame_json" OR NEW."llm_use_id" IS NOT OLD."llm_use_id" OR NEW."received_at" IS NOT OLD."received_at" OR NEW."seq" IS NOT OLD."seq"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_model_response_frames_history_retained" BEFORE DELETE ON "code_model_response_frames"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_task_reservations_identity_fixed" BEFORE UPDATE ON "code_task_reservations"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."llm_use_id" IS NOT OLD."llm_use_id" OR NEW."price_version_id" IS NOT OLD."price_version_id" OR NEW."reserved_cny" IS NOT OLD."reserved_cny" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_task_reservations_history_retained" BEFORE DELETE ON "code_task_reservations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_task_reservations_settled_cny_fixed" BEFORE UPDATE ON "code_task_reservations"
WHEN OLD."settled_cny" IS NOT NULL AND NEW."settled_cny" IS NOT OLD."settled_cny"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_task_reservations_settled_at_fixed" BEFORE UPDATE ON "code_task_reservations"
WHEN OLD."settled_at" IS NOT NULL AND NEW."settled_at" IS NOT OLD."settled_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_task_reservations_settlement_basis_fixed" BEFORE UPDATE ON "code_task_reservations"
WHEN OLD."settlement_basis" IS NOT NULL AND NEW."settlement_basis" IS NOT OLD."settlement_basis"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "model_price_versions_identity_fixed" BEFORE UPDATE ON "model_price_versions"
WHEN NEW."billing_scope_ref" IS NOT OLD."billing_scope_ref" OR NEW."cache_price_rules" IS NOT OLD."cache_price_rules" OR NEW."channel" IS NOT OLD."channel" OR NEW."currency" IS NOT OLD."currency" OR NEW."id" IS NOT OLD."id" OR NEW."input_price_per_million" IS NOT OLD."input_price_per_million" OR NEW."model_profile_ref" IS NOT OLD."model_profile_ref" OR NEW."model_snapshot_ref" IS NOT OLD."model_snapshot_ref" OR NEW."output_price_per_million" IS NOT OLD."output_price_per_million" OR NEW."rounding_rule" IS NOT OLD."rounding_rule" OR NEW."service_tier" IS NOT OLD."service_tier" OR NEW."source_ref" IS NOT OLD."source_ref" OR NEW."tariff_rules" IS NOT OLD."tariff_rules" OR NEW."valid_from" IS NOT OLD."valid_from" OR NEW."valid_until" IS NOT OLD."valid_until" OR NEW."verified_at" IS NOT OLD."verified_at"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "model_price_versions_history_retained" BEFORE DELETE ON "model_price_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "model_usage_evidence_identity_fixed" BEFORE UPDATE ON "model_usage_evidence"
WHEN NEW."external_evidence_id" IS NOT OLD."external_evidence_id" OR NEW."id" IS NOT OLD."id" OR NEW."llm_use_id" IS NOT OLD."llm_use_id" OR NEW."received_at" IS NOT OLD."received_at" OR NEW."source_ref" IS NOT OLD."source_ref" OR NEW."usage" IS NOT OLD."usage"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "model_usage_evidence_history_retained" BEFORE DELETE ON "model_usage_evidence"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_questions_identity_fixed" BEFORE UPDATE ON "code_questions"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."id" IS NOT OLD."id" OR NEW."instance_id" IS NOT OLD."instance_id" OR NEW."native_question_id" IS NOT OLD."native_question_id" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."questions" IS NOT OLD."questions" OR NEW."session_id" IS NOT OLD."session_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_questions_history_retained" BEFORE DELETE ON "code_questions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_permissions_identity_fixed" BEFORE UPDATE ON "code_permissions"
WHEN NEW."control_generation" IS NOT OLD."control_generation" OR NEW."id" IS NOT OLD."id" OR NEW."instance_id" IS NOT OLD."instance_id" OR NEW."native_observation" IS NOT OLD."native_observation" OR NEW."native_permission_id" IS NOT OLD."native_permission_id" OR NEW."object_refs" IS NOT OLD."object_refs" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."patterns" IS NOT OLD."patterns" OR NEW."requested_action" IS NOT OLD."requested_action" OR NEW."session_id" IS NOT OLD."session_id" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."tool_name" IS NOT OLD."tool_name" OR NEW."tool_ref" IS NOT OLD."tool_ref"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_permissions_history_retained" BEFORE DELETE ON "code_permissions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_question_handoffs_identity_fixed" BEFORE UPDATE ON "code_question_handoffs"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."question_id" IS NOT OLD."question_id" OR NEW."target_document_id" IS NOT OLD."target_document_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_question_handoffs_history_retained" BEFORE DELETE ON "code_question_handoffs"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_question_handoff_events_identity_fixed" BEFORE UPDATE ON "code_question_handoff_events"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."guide_run_id" IS NOT OLD."guide_run_id" OR NEW."handoff_id" IS NOT OLD."handoff_id" OR NEW."id" IS NOT OLD."id" OR NEW."kind" IS NOT OLD."kind" OR NEW."message_id" IS NOT OLD."message_id" OR NEW."revision_id" IS NOT OLD."revision_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_question_handoff_events_history_retained" BEFORE DELETE ON "code_question_handoff_events"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_repositories_identity_fixed" BEFORE UPDATE ON "code_repositories"
WHEN NEW."canonical_root" IS NOT OLD."canonical_root" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."git_common_dir" IS NOT OLD."git_common_dir" OR NEW."id" IS NOT OLD."id" OR NEW."name" IS NOT OLD."name" OR NEW."object_format" IS NOT OLD."object_format"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_repositories_history_retained" BEFORE DELETE ON "code_repositories"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_repository_observations_identity_fixed" BEFORE UPDATE ON "code_repository_observations"
WHEN NEW."head_commit" IS NOT OLD."head_commit" OR NEW."id" IS NOT OLD."id" OR NEW."local_branches" IS NOT OLD."local_branches" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."status" IS NOT OLD."status" OR NEW."worktrees" IS NOT OLD."worktrees"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_repository_observations_history_retained" BEFORE DELETE ON "code_repository_observations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_tasks_identity_fixed" BEFORE UPDATE ON "testing_tasks"
WHEN NEW."authorization_id" IS NOT OLD."authorization_id" OR NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."id" IS NOT OLD."id" OR NEW."kind" IS NOT OLD."kind" OR NEW."previous_testing_task_id" IS NOT OLD."previous_testing_task_id" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."purpose" IS NOT OLD."purpose" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."snapshot_id" IS NOT OLD."snapshot_id" OR NEW."target_kind" IS NOT OLD."target_kind" OR NEW."validation_id" IS NOT OLD."validation_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_tasks_history_retained" BEFORE DELETE ON "testing_tasks"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_tasks_report_id_fixed" BEFORE UPDATE ON "testing_tasks"
WHEN OLD."report_id" IS NOT NULL AND NEW."report_id" IS NOT OLD."report_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_plans_identity_fixed" BEFORE UPDATE ON "testing_plans"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."name" IS NOT OLD."name"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_plans_history_retained" BEFORE DELETE ON "testing_plans"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_plan_versions_identity_fixed" BEFORE UPDATE ON "testing_plan_versions"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."id" IS NOT OLD."id" OR NEW."plan_id" IS NOT OLD."plan_id" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."version" IS NOT OLD."version"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_plan_versions_history_retained" BEFORE DELETE ON "testing_plan_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_plan_versions_published_at_fixed" BEFORE UPDATE ON "testing_plan_versions"
WHEN OLD."published_at" IS NOT NULL AND NEW."published_at" IS NOT OLD."published_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_plan_versions_revoked_at_fixed" BEFORE UPDATE ON "testing_plan_versions"
WHEN OLD."revoked_at" IS NOT NULL AND NEW."revoked_at" IS NOT OLD."revoked_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_plan_versions_revocation_reason_fixed" BEFORE UPDATE ON "testing_plan_versions"
WHEN OLD."revocation_reason" IS NOT NULL AND NEW."revocation_reason" IS NOT OLD."revocation_reason"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_pack_versions_identity_fixed" BEFORE UPDATE ON "testing_pack_versions"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."plan_version_id" IS NOT OLD."plan_version_id" OR NEW."version" IS NOT OLD."version"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_pack_versions_history_retained" BEFORE DELETE ON "testing_pack_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_pack_versions_published_at_fixed" BEFORE UPDATE ON "testing_pack_versions"
WHEN OLD."published_at" IS NOT NULL AND NEW."published_at" IS NOT OLD."published_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_pack_versions_revoked_at_fixed" BEFORE UPDATE ON "testing_pack_versions"
WHEN OLD."revoked_at" IS NOT NULL AND NEW."revoked_at" IS NOT OLD."revoked_at"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_pack_versions_revocation_reason_fixed" BEFORE UPDATE ON "testing_pack_versions"
WHEN OLD."revocation_reason" IS NOT NULL AND NEW."revocation_reason" IS NOT OLD."revocation_reason"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_pack_validations_identity_fixed" BEFORE UPDATE ON "testing_pack_validations"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."reference_set_ref" IS NOT OLD."reference_set_ref" OR NEW."test_pack_version_id" IS NOT OLD."test_pack_version_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_pack_validations_history_retained" BEFORE DELETE ON "testing_pack_validations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_reports_identity_fixed" BEFORE UPDATE ON "testing_reports"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."input_fingerprint" IS NOT OLD."input_fingerprint" OR NEW."manual_coverage_ids" IS NOT OLD."manual_coverage_ids" OR NEW."plan_version_id" IS NOT OLD."plan_version_id" OR NEW."result" IS NOT OLD."result" OR NEW."scope_stages" IS NOT OLD."scope_stages" OR NEW."test_pack_version_id" IS NOT OLD."test_pack_version_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id" OR NEW."uncovered_behavior_ids" IS NOT OLD."uncovered_behavior_ids" OR NEW."verification_id" IS NOT OLD."verification_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_reports_history_retained" BEFORE DELETE ON "testing_reports"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_findings_identity_fixed" BEFORE UPDATE ON "testing_findings"
WHEN NEW."actual_behavior" IS NOT OLD."actual_behavior" OR NEW."basis_ref" IS NOT OLD."basis_ref" OR NEW."case_id" IS NOT OLD."case_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."expected_behavior" IS NOT OLD."expected_behavior" OR NEW."id" IS NOT OLD."id" OR NEW."item_id" IS NOT OLD."item_id" OR NEW."test_report_id" IS NOT OLD."test_report_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_findings_history_retained" BEFORE DELETE ON "testing_findings"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_profile_versions_identity_fixed" BEFORE UPDATE ON "testing_profile_versions"
WHEN NEW."admission_refs" IS NOT OLD."admission_refs" OR NEW."commands" IS NOT OLD."commands" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."environment_refs" IS NOT OLD."environment_refs" OR NEW."id" IS NOT OLD."id" OR NEW."limits" IS NOT OLD."limits" OR NEW."model_binding" IS NOT OLD."model_binding" OR NEW."name" IS NOT OLD."name" OR NEW."runner_refs" IS NOT OLD."runner_refs" OR NEW."version" IS NOT OLD."version"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_profile_versions_history_retained" BEFORE DELETE ON "testing_profile_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_authorizations_identity_fixed" BEFORE UPDATE ON "testing_authorizations"
WHEN NEW."actor_ref" IS NOT OLD."actor_ref" OR NEW."approved_at" IS NOT OLD."approved_at" OR NEW."budget_limit_cny" IS NOT OLD."budget_limit_cny" OR NEW."id" IS NOT OLD."id" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."scope_kind" IS NOT OLD."scope_kind"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_authorizations_history_retained" BEFORE DELETE ON "testing_authorizations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_authorizations_testing_task_id_fixed" BEFORE UPDATE ON "testing_authorizations"
WHEN OLD."testing_task_id" IS NOT NULL AND NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "testing_authorizations_validation_id_fixed" BEFORE UPDATE ON "testing_authorizations"
WHEN OLD."validation_id" IS NOT NULL AND NEW."validation_id" IS NOT OLD."validation_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_execution_profiles_identity_fixed" BEFORE UPDATE ON "code_execution_profiles"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."name" IS NOT OLD."name"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_execution_profiles_history_retained" BEFORE DELETE ON "code_execution_profiles"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_check_sets_identity_fixed" BEFORE UPDATE ON "code_check_sets"
WHEN NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."name" IS NOT OLD."name"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_check_sets_history_retained" BEFORE DELETE ON "code_check_sets"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_check_set_versions_identity_fixed" BEFORE UPDATE ON "code_check_set_versions"
WHEN NEW."check_set_id" IS NOT OLD."check_set_id" OR NEW."coverage_plan" IS NOT OLD."coverage_plan" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."items" IS NOT OLD."items" OR NEW."owner_module" IS NOT OLD."owner_module" OR NEW."protocol_version" IS NOT OLD."protocol_version" OR NEW."version" IS NOT OLD."version"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_check_set_versions_history_retained" BEFORE DELETE ON "code_check_set_versions"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_authorizations_identity_fixed" BEFORE UPDATE ON "code_authorizations"
WHEN NEW."actor_ref" IS NOT OLD."actor_ref" OR NEW."approved_at" IS NOT OLD."approved_at" OR NEW."id" IS NOT OLD."id" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."scope" IS NOT OLD."scope"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_authorizations_history_retained" BEFORE DELETE ON "code_authorizations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_authorizations_task_id_fixed" BEFORE UPDATE ON "code_authorizations"
WHEN OLD."task_id" IS NOT NULL AND NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'ORIGINAL_FACT_IS_FIXED'); END;

CREATE TRIGGER "code_configuration_applications_identity_fixed" BEFORE UPDATE ON "code_configuration_applications"
WHEN NEW."authorization_id" IS NOT OLD."authorization_id" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."new_profile_version_id" IS NOT OLD."new_profile_version_id" OR NEW."old_profile_version_id" IS NOT OLD."old_profile_version_id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_configuration_applications_history_retained" BEFORE DELETE ON "code_configuration_applications"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_runtime_observations_identity_fixed" BEFORE UPDATE ON "code_runtime_observations"
WHEN NEW."active_process_count" IS NOT OLD."active_process_count" OR NEW."command_id" IS NOT OLD."command_id" OR NEW."control_generation" IS NOT OLD."control_generation" OR NEW."evidence_ref" IS NOT OLD."evidence_ref" OR NEW."id" IS NOT OLD."id" OR NEW."instance_id" IS NOT OLD."instance_id" OR NEW."kind" IS NOT OLD."kind" OR NEW."observed_at" IS NOT OLD."observed_at" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."reason_codes" IS NOT OLD."reason_codes" OR NEW."result" IS NOT OLD."result" OR NEW."runtime_binding_ref" IS NOT OLD."runtime_binding_ref" OR NEW."task_id" IS NOT OLD."task_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_runtime_observations_history_retained" BEFORE DELETE ON "code_runtime_observations"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_task_materials_identity_fixed" BEFORE UPDATE ON "code_task_materials"
WHEN NEW."document_id" IS NOT OLD."document_id" OR NEW."revision_id" IS NOT OLD."revision_id" OR NEW."task_id" IS NOT OLD."task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_task_materials_history_retained" BEFORE DELETE ON "code_task_materials"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_repair_defects_identity_fixed" BEFORE UPDATE ON "code_repair_defects"
WHEN NEW."defect_id" IS NOT OLD."defect_id" OR NEW."repair_id" IS NOT OLD."repair_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_repair_defects_history_retained" BEFORE DELETE ON "code_repair_defects"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_task_materials_identity_fixed" BEFORE UPDATE ON "testing_task_materials"
WHEN NEW."document_id" IS NOT OLD."document_id" OR NEW."revision_id" IS NOT OLD."revision_id" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_task_materials_history_retained" BEFORE DELETE ON "testing_task_materials"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_plan_materials_identity_fixed" BEFORE UPDATE ON "testing_plan_materials"
WHEN NEW."document_id" IS NOT OLD."document_id" OR NEW."plan_version_id" IS NOT OLD."plan_version_id" OR NEW."revision_id" IS NOT OLD."revision_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_plan_materials_history_retained" BEFORE DELETE ON "testing_plan_materials"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "testing_validation_tasks_identity_fixed" BEFORE UPDATE ON "testing_validation_tasks"
WHEN NEW."testing_task_id" IS NOT OLD."testing_task_id" OR NEW."validation_id" IS NOT OLD."validation_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "testing_validation_tasks_history_retained" BEFORE DELETE ON "testing_validation_tasks"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_schema_state_identity_fixed" BEFORE UPDATE ON "code_schema_state"
WHEN NEW."committed_at" IS NOT OLD."committed_at" OR NEW."origin" IS NOT OLD."origin" OR NEW."schema_contract_sha256" IS NOT OLD."schema_contract_sha256" OR NEW."schema_version" IS NOT OLD."schema_version" OR NEW."singleton_id" IS NOT OLD."singleton_id" OR NEW."source_data_sha256" IS NOT OLD."source_data_sha256" OR NEW."upgrade_id" IS NOT OLD."upgrade_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_schema_state_history_retained" BEFORE DELETE ON "code_schema_state"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_defect_evidence_refs_identity_fixed" BEFORE UPDATE ON "code_defect_evidence_refs"
WHEN NEW."defect_id" IS NOT OLD."defect_id" OR NEW."kind" IS NOT OLD."kind" OR NEW."ordinal" IS NOT OLD."ordinal" OR NEW."source_id" IS NOT OLD."source_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER "code_defect_evidence_refs_history_retained" BEFORE DELETE ON "code_defect_evidence_refs"
WHEN 1
BEGIN SELECT RAISE(ABORT,'HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_tasks_terminal_fixed" BEFORE UPDATE ON "code_tasks"
WHEN OLD.status IN ('COMPLETED','TERMINATED') AND (NEW."active_session_id" IS NOT OLD."active_session_id" OR NEW."authorization_id" IS NOT OLD."authorization_id" OR NEW."base_snapshot_id" IS NOT OLD."base_snapshot_id" OR NEW."budget_limit_cny" IS NOT OLD."budget_limit_cny" OR NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."current_candidate_id" IS NOT OLD."current_candidate_id" OR NEW."current_delivery_id" IS NOT OLD."current_delivery_id" OR NEW."current_delivery_plan_id" IS NOT OLD."current_delivery_plan_id" OR NEW."current_test_report_id" IS NOT OLD."current_test_report_id" OR NEW."current_verification_id" IS NOT OLD."current_verification_id" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."ended_at" IS NOT OLD."ended_at" OR NEW."execution_profile_version_id" IS NOT OLD."execution_profile_version_id" OR NEW."id" IS NOT OLD."id" OR NEW."phase" IS NOT OLD."phase" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."resume_phase" IS NOT OLD."resume_phase" OR NEW."started_at" IS NOT OLD."started_at" OR NEW."state_version" IS NOT OLD."state_version" OR NEW."status" IS NOT OLD."status" OR NEW."stop_requested_at" IS NOT OLD."stop_requested_at" OR NEW."stopped_at" IS NOT OLD."stopped_at" OR NEW."target_branch" IS NOT OLD."target_branch" OR NEW."workspace_id" IS NOT OLD."workspace_id")
BEGIN SELECT RAISE(ABORT,'TASK_ENDED'); END;

CREATE TRIGGER "testing_tasks_terminal_fixed" BEFORE UPDATE ON "testing_tasks"
WHEN OLD.status IN ('COMPLETED','TERMINATED') AND (NEW."active_operation_id" IS NOT OLD."active_operation_id" OR NEW."authorization_id" IS NOT OLD."authorization_id" OR NEW."budget_limit_cny" IS NOT OLD."budget_limit_cny" OR NEW."candidate_id" IS NOT OLD."candidate_id" OR NEW."control_generation" IS NOT OLD."control_generation" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."current_verification_id" IS NOT OLD."current_verification_id" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."draft_plan_operation_id" IS NOT OLD."draft_plan_operation_id" OR NEW."ended_at" IS NOT OLD."ended_at" OR NEW."id" IS NOT OLD."id" OR NEW."kind" IS NOT OLD."kind" OR NEW."phase" IS NOT OLD."phase" OR NEW."plan_version_id" IS NOT OLD."plan_version_id" OR NEW."previous_testing_task_id" IS NOT OLD."previous_testing_task_id" OR NEW."profile_version_id" IS NOT OLD."profile_version_id" OR NEW."purpose" IS NOT OLD."purpose" OR NEW."report_id" IS NOT OLD."report_id" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."snapshot_id" IS NOT OLD."snapshot_id" OR NEW."state_version" IS NOT OLD."state_version" OR NEW."status" IS NOT OLD."status" OR NEW."stop_requested_at" IS NOT OLD."stop_requested_at" OR NEW."stopped_at" IS NOT OLD."stopped_at" OR NEW."target_kind" IS NOT OLD."target_kind" OR NEW."test_pack_version_id" IS NOT OLD."test_pack_version_id" OR NEW."validation_id" IS NOT OLD."validation_id")
BEGIN SELECT RAISE(ABORT,'TASK_ENDED'); END;

CREATE TRIGGER "testing_plan_versions_published_input_fixed" BEFORE UPDATE ON "testing_plan_versions"
WHEN OLD.status IN ('PUBLISHED','REVOKED') AND (NEW."behaviors" IS NOT OLD."behaviors" OR NEW."cases" IS NOT OLD."cases" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."design_revision_id" IS NOT OLD."design_revision_id" OR NEW."document_id" IS NOT OLD."document_id" OR NEW."id" IS NOT OLD."id" OR NEW."plan_id" IS NOT OLD."plan_id" OR NEW."requirement_id" IS NOT OLD."requirement_id" OR NEW."unresolved_questions" IS NOT OLD."unresolved_questions" OR NEW."version" IS NOT OLD."version")
BEGIN SELECT RAISE(ABORT,'PUBLISHED_RESOURCE_IS_FIXED'); END;

CREATE TRIGGER "testing_pack_versions_published_input_fixed" BEFORE UPDATE ON "testing_pack_versions"
WHEN OLD.status IN ('SEALED','PUBLISHED','REVOKED') AND (NEW."check_set_version_id" IS NOT OLD."check_set_version_id" OR NEW."content_ref" IS NOT OLD."content_ref" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."plan_version_id" IS NOT OLD."plan_version_id" OR NEW."sha256" IS NOT OLD."sha256" OR NEW."version" IS NOT OLD."version")
BEGIN SELECT RAISE(ABORT,'PUBLISHED_RESOURCE_IS_FIXED'); END;

CREATE TRIGGER "idempotency_v2_unknown_retained" BEFORE DELETE ON "idempotency_records"
WHEN OLD.status='PROCESSING' AND (OLD.capability_id GLOB 'APP-CODE-CMD-C[0-9][0-9]' OR OLD.capability_id GLOB 'APP-TEST-CMD-C[0-9][0-9]')
BEGIN SELECT RAISE(ABORT,'UNKNOWN_RECEIPT_MUST_BE_RETAINED'); END;

CREATE TRIGGER "idempotency_v2_terminal_fixed" BEFORE UPDATE ON "idempotency_records"
WHEN OLD.status IN ('REJECTED','CLOSED')
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TERMINAL_RECEIPT'); END;

CREATE TRIGGER "idempotency_v2_terminal_retained" BEFORE DELETE ON "idempotency_records"
WHEN OLD.status IN ('REJECTED','CLOSED')
BEGIN SELECT RAISE(ABORT,'TERMINAL_RECEIPT_MUST_BE_RETAINED'); END;

CREATE TRIGGER "llm_v2_identity_fixed" BEFORE UPDATE ON "llm_uses"
WHEN NEW."attempt_no" IS NOT OLD."attempt_no" OR NEW."call_no" IS NOT OLD."call_no" OR NEW."call_purpose" IS NOT OLD."call_purpose" OR NEW."execution_session_id" IS NOT OLD."execution_session_id" OR NEW."gateway_request_id" IS NOT OLD."gateway_request_id" OR NEW."operation_id" IS NOT OLD."operation_id" OR NEW."protocol_version" IS NOT OLD."protocol_version" OR NEW."retry_of_llm_use_id" IS NOT OLD."retry_of_llm_use_id" OR NEW."source_evidence_ref" IS NOT OLD."source_evidence_ref" OR NEW."testing_task_id" IS NOT OLD."testing_task_id"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CALL_OWNER'); END;

CREATE TRIGGER "llm_v2_evidence_retained" BEFORE DELETE ON "llm_uses"
WHEN OLD.guide_run_id IS NULL
BEGIN SELECT RAISE(ABORT,'CALL_EVIDENCE_MUST_BE_RETAINED'); END;

CREATE TRIGGER "code_candidates_owner_insert" BEFORE INSERT ON "code_candidates"
WHEN NOT EXISTS(SELECT 1 FROM code_tasks t WHERE t.id=NEW.task_id AND t.base_snapshot_id=NEW.base_snapshot_id)
BEGIN SELECT RAISE(ABORT,'CANDIDATE_BASE_MISMATCH'); END;

CREATE TRIGGER "code_candidates_owner_update" BEFORE UPDATE ON "code_candidates"
WHEN NOT EXISTS(SELECT 1 FROM code_tasks t WHERE t.id=NEW.task_id AND t.base_snapshot_id=NEW.base_snapshot_id)
BEGIN SELECT RAISE(ABORT,'CANDIDATE_BASE_MISMATCH'); END;

CREATE TRIGGER "code_snapshots_owner_insert" BEFORE INSERT ON "code_snapshots"
WHEN NOT EXISTS(SELECT 1 FROM code_repositories r WHERE r.id=NEW.repository_id AND length(NEW.commit_oid)=CASE r.object_format WHEN 'sha1' THEN 40 WHEN 'sha256' THEN 64 END AND length(NEW.content_tree_oid)=length(NEW.commit_oid))
BEGIN SELECT RAISE(ABORT,'REPOSITORY_OBJECT_FORMAT_MISMATCH'); END;

CREATE TRIGGER "code_snapshots_owner_update" BEFORE UPDATE ON "code_snapshots"
WHEN NOT EXISTS(SELECT 1 FROM code_repositories r WHERE r.id=NEW.repository_id AND length(NEW.commit_oid)=CASE r.object_format WHEN 'sha1' THEN 40 WHEN 'sha256' THEN 64 END AND length(NEW.content_tree_oid)=length(NEW.commit_oid))
BEGIN SELECT RAISE(ABORT,'REPOSITORY_OBJECT_FORMAT_MISMATCH'); END;

CREATE TRIGGER "code_acceptances_owner_insert" BEFORE INSERT ON "code_acceptances"
WHEN NOT EXISTS(SELECT 1 FROM testing_reports r WHERE r.id=NEW.test_report_id AND NEW.manual_risk_accepted=(json_array_length(r.manual_coverage_ids)>0))
BEGIN SELECT RAISE(ABORT,'MANUAL_RISK_ACCEPTANCE_MISMATCH'); END;

CREATE TRIGGER "code_acceptances_owner_update" BEFORE UPDATE ON "code_acceptances"
WHEN NOT EXISTS(SELECT 1 FROM testing_reports r WHERE r.id=NEW.test_report_id AND NEW.manual_risk_accepted=(json_array_length(r.manual_coverage_ids)>0))
BEGIN SELECT RAISE(ABORT,'MANUAL_RISK_ACCEPTANCE_MISMATCH'); END;

CREATE TRIGGER "code_task_reservations_owner_insert" BEFORE INSERT ON "code_task_reservations"
WHEN NOT EXISTS(SELECT 1 FROM llm_uses u LEFT JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.llm_use_id AND ((NEW.task_id IS NOT NULL AND s.task_id=NEW.task_id AND u.testing_task_id IS NULL) OR (NEW.testing_task_id IS NOT NULL AND u.testing_task_id=NEW.testing_task_id AND u.execution_session_id IS NULL)))
BEGIN SELECT RAISE(ABORT,'CALL_RESERVATION_OWNER_MISMATCH'); END;

CREATE TRIGGER "code_task_reservations_owner_update" BEFORE UPDATE ON "code_task_reservations"
WHEN NOT EXISTS(SELECT 1 FROM llm_uses u LEFT JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.llm_use_id AND ((NEW.task_id IS NOT NULL AND s.task_id=NEW.task_id AND u.testing_task_id IS NULL) OR (NEW.testing_task_id IS NOT NULL AND u.testing_task_id=NEW.testing_task_id AND u.execution_session_id IS NULL)))
BEGIN SELECT RAISE(ABORT,'CALL_RESERVATION_OWNER_MISMATCH'); END;

CREATE TRIGGER "llm_uses_owner_insert" BEFORE INSERT ON "llm_uses"
WHEN (NEW.execution_session_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o JOIN code_sessions s ON s.id=NEW.execution_session_id WHERE o.id=NEW.operation_id AND o.task_id=s.task_id AND o.testing_task_id IS NULL)) OR (NEW.testing_task_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.operation_id AND o.testing_task_id=NEW.testing_task_id AND o.task_id IS NULL)) OR (NEW.retry_of_llm_use_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM llm_uses p WHERE p.id=NEW.retry_of_llm_use_id AND p.execution_session_id IS NEW.execution_session_id AND p.testing_task_id IS NEW.testing_task_id AND p.call_no<NEW.call_no))
BEGIN SELECT RAISE(ABORT,'CALL_OPERATION_OWNER_MISMATCH'); END;

CREATE TRIGGER "llm_uses_owner_update" BEFORE UPDATE ON "llm_uses"
WHEN (NEW.execution_session_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o JOIN code_sessions s ON s.id=NEW.execution_session_id WHERE o.id=NEW.operation_id AND o.task_id=s.task_id AND o.testing_task_id IS NULL)) OR (NEW.testing_task_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.operation_id AND o.testing_task_id=NEW.testing_task_id AND o.task_id IS NULL)) OR (NEW.retry_of_llm_use_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM llm_uses p WHERE p.id=NEW.retry_of_llm_use_id AND p.execution_session_id IS NEW.execution_session_id AND p.testing_task_id IS NEW.testing_task_id AND p.call_no<NEW.call_no))
BEGIN SELECT RAISE(ABORT,'CALL_OPERATION_OWNER_MISMATCH'); END;

CREATE TRIGGER "code_defect_evidence_owner" BEFORE INSERT ON "code_defect_evidence_refs"
WHEN NOT EXISTS(SELECT 1 FROM code_defects d WHERE d.id=NEW.defect_id AND ((NEW.kind='OPERATION' AND EXISTS(SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND s.task_id=d.task_id)) OR (NEW.kind='COMMAND' AND EXISTS(SELECT 1 FROM code_commands s WHERE s.id=NEW.source_id AND s.task_id=d.task_id)) OR (NEW.kind='QUESTION' AND EXISTS(SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=d.task_id)) OR (NEW.kind='VERIFICATION_ITEM' AND EXISTS(SELECT 1 FROM code_verification_items i JOIN code_verifications s ON s.id=i.verification_id WHERE i.id=NEW.source_id AND s.task_id=d.task_id)) OR (NEW.kind='LLM_USE' AND EXISTS(SELECT 1 FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.source_id AND s.task_id=d.task_id)))) OR (NEW.ordinal>1 AND NOT EXISTS(SELECT 1 FROM code_defect_evidence_refs p WHERE p.defect_id=NEW.defect_id AND p.ordinal=NEW.ordinal-1))
BEGIN SELECT RAISE(ABORT,'DEFECT_EVIDENCE_OWNER_MISMATCH'); END;

CREATE TRIGGER "code_defect_fixed_basis" BEFORE INSERT ON "code_defects"
WHEN NOT EXISTS(SELECT 1 FROM revisions r WHERE r.id=NEW.basis_revision_id AND r.document_id=NEW.basis_document_id AND instr(r.markdown_snapshot,json_extract(NEW.basis_ref,'$.quote'))>0 AND (EXISTS(SELECT 1 FROM code_tasks t WHERE t.id=NEW.task_id AND t.document_id=r.document_id AND t.design_revision_id=r.id) OR EXISTS(SELECT 1 FROM code_task_materials m WHERE m.task_id=NEW.task_id AND m.document_id=r.document_id AND m.revision_id=r.id)))
BEGIN SELECT RAISE(ABORT,'BASIS_REF_INVALID'); END;

CREATE TRIGGER "code_operation_resource_exists" BEFORE INSERT ON "code_operations"
WHEN (NEW.resource_kind='TASK' AND NOT EXISTS(SELECT 1 FROM code_tasks s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TESTING_TASK' AND NOT EXISTS(SELECT 1 FROM testing_tasks s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_PLAN' AND NOT EXISTS(SELECT 1 FROM testing_plans s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_PLAN_VERSION' AND NOT EXISTS(SELECT 1 FROM testing_plan_versions s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_PACK_VERSION' AND NOT EXISTS(SELECT 1 FROM testing_pack_versions s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_PROFILE_VERSION' AND NOT EXISTS(SELECT 1 FROM testing_profile_versions s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_AUTHORIZATION' AND NOT EXISTS(SELECT 1 FROM testing_authorizations s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TEST_REPORT' AND NOT EXISTS(SELECT 1 FROM testing_reports s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='TESTING_FINDING' AND NOT EXISTS(SELECT 1 FROM testing_findings s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='REPOSITORY' AND NOT EXISTS(SELECT 1 FROM code_repositories s WHERE s.id=NEW.resource_id) AND NOT COALESCE((NEW.operation_type='REGISTER_REPOSITORY' AND NEW.task_id IS NULL AND NEW.testing_task_id IS NULL AND NEW.session_id IS NULL AND NEW.control_generation IS NULL AND NEW.expected_state_version IS NULL AND NEW.status='PENDING' AND EXISTS(SELECT 1 FROM sequences q WHERE q.entity_kind='CodeRepository' AND q.last_value=NEW.resource_id) AND json_type(NEW.fixed_input,'$.name')='text' AND json_type(NEW.fixed_input,'$.root_path')='text' AND (SELECT count(*) FROM json_each(NEW.fixed_input))=2 AND EXISTS(SELECT 1 FROM idempotency_records i WHERE i.capability_id='APP-CODE-CMD-C01' AND i.target_identity='POST /api/v1/code-repositories' AND i.idempotency_key=NEW.idempotency_key AND i.status='PROCESSING' AND i.business_input_json=NEW.fixed_input)),0)) OR (NEW.resource_kind='SNAPSHOT' AND NOT EXISTS(SELECT 1 FROM code_snapshots s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='EXECUTION_PROFILE' AND NOT EXISTS(SELECT 1 FROM code_execution_profiles s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='EXECUTION_PROFILE_VERSION' AND NOT EXISTS(SELECT 1 FROM code_execution_profile_versions s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='CHECK_SET' AND NOT EXISTS(SELECT 1 FROM code_check_sets s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='CHECK_SET_VERSION' AND NOT EXISTS(SELECT 1 FROM code_check_set_versions s WHERE s.id=NEW.resource_id)) OR (NEW.resource_kind='AUTHORIZATION' AND NOT EXISTS(SELECT 1 FROM code_authorizations s WHERE s.id=NEW.resource_id))
BEGIN SELECT RAISE(ABORT,'OPERATION_RESOURCE_MISSING'); END;

CREATE TRIGGER "code_waiting_source_exists" BEFORE INSERT ON "code_waiting_items"
WHEN (NEW.source_kind='OPERATION' AND NOT EXISTS(SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND s.task_id IS NEW.task_id AND s.testing_task_id IS NEW.testing_task_id)) OR (NEW.source_kind='QUESTION' AND NOT EXISTS(SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL)) OR (NEW.source_kind='PERMISSION' AND NOT EXISTS(SELECT 1 FROM code_permissions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL)) OR (NEW.source_kind='VERIFICATION_ITEM' AND NOT EXISTS(SELECT 1 FROM code_verification_items i JOIN code_verifications s ON s.id=i.verification_id WHERE i.id=NEW.source_id AND s.task_id IS NEW.task_id AND s.testing_task_id IS NEW.testing_task_id)) OR (NEW.source_kind='LLM_USE' AND NOT EXISTS(SELECT 1 FROM llm_uses u LEFT JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.source_id AND ((NEW.task_id IS NOT NULL AND s.task_id=NEW.task_id) OR (NEW.testing_task_id IS NOT NULL AND u.testing_task_id=NEW.testing_task_id)))) OR (NEW.source_kind='DELIVERY' AND NOT EXISTS(SELECT 1 FROM code_deliveries s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL))
BEGIN SELECT RAISE(ABORT,'WAITING_SOURCE_OWNER_MISMATCH'); END;

CREATE TRIGGER "code_record_source_fixed" BEFORE INSERT ON "code_execution_records"
WHEN (NEW.source_kind='OPERATION' AND NOT EXISTS(SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id)) OR (NEW.source_kind='COMMAND' AND NOT EXISTS(SELECT 1 FROM code_commands s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id)) OR (NEW.source_kind='QUESTION' AND NOT EXISTS(SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id)) OR (NEW.source_kind='PERMISSION' AND NOT EXISTS(SELECT 1 FROM code_permissions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id)) OR (NEW.source_kind='LLM_USE' AND NOT EXISTS(SELECT 1 FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.source_id AND s.task_id=NEW.task_id))
BEGIN SELECT RAISE(ABORT,'OBSERVATION_SOURCE_OWNER_MISMATCH'); END;

CREATE TRIGGER "code_operations_terminal_status_fixed" BEFORE UPDATE ON "code_operations"
WHEN OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW.status IS NOT OLD.status
BEGIN SELECT RAISE(ABORT,'TERMINAL_OPERATION_IS_FIXED'); END;

CREATE TRIGGER "code_commands_terminal_status_fixed" BEFORE UPDATE ON "code_commands"
WHEN OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW.status IS NOT OLD.status
BEGIN SELECT RAISE(ABORT,'TERMINAL_OPERATION_IS_FIXED'); END;

CREATE TRIGGER "code_repairs_terminal_status_fixed" BEFORE UPDATE ON "code_repairs"
WHEN OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW.status IS NOT OLD.status
BEGIN SELECT RAISE(ABORT,'TERMINAL_OPERATION_IS_FIXED'); END;

CREATE TRIGGER "code_verification_handoff_insert" BEFORE INSERT ON "code_verifications"
WHEN NEW.owner_kind='CODING' AND (NOT EXISTS(SELECT 1 FROM code_candidates c WHERE c.id=NEW.candidate_id AND c.task_id=NEW.task_id AND c.role=NEW.role) OR NOT EXISTS(SELECT 1 FROM code_check_set_versions s JOIN code_execution_profile_versions p ON p.id=NEW.profile_version_id WHERE s.id=NEW.check_set_version_id AND p.check_set_version_id=s.id AND s.owner_module='CODING') OR (NEW.backend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.backend_handoff_operation_id AND o.task_id=NEW.task_id AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED')) OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.frontend_handoff_operation_id AND o.task_id=NEW.task_id AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED')) OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations b JOIN code_operations f ON f.id=NEW.frontend_handoff_operation_id WHERE b.id=NEW.backend_handoff_operation_id AND b.id<>f.id AND b.created_at<=f.created_at)))
BEGIN SELECT RAISE(ABORT,'VERIFICATION_STAGE_NOT_READY'); END;

CREATE TRIGGER "code_verification_handoff_update" BEFORE UPDATE ON "code_verifications"
WHEN NEW.owner_kind='CODING' AND (NOT EXISTS(SELECT 1 FROM code_candidates c WHERE c.id=NEW.candidate_id AND c.task_id=NEW.task_id AND c.role=NEW.role) OR NOT EXISTS(SELECT 1 FROM code_check_set_versions s JOIN code_execution_profile_versions p ON p.id=NEW.profile_version_id WHERE s.id=NEW.check_set_version_id AND p.check_set_version_id=s.id AND s.owner_module='CODING') OR (NEW.backend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.backend_handoff_operation_id AND o.task_id=NEW.task_id AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED')) OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.frontend_handoff_operation_id AND o.task_id=NEW.task_id AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED')) OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations b JOIN code_operations f ON f.id=NEW.frontend_handoff_operation_id WHERE b.id=NEW.backend_handoff_operation_id AND b.id<>f.id AND b.created_at<=f.created_at)))
BEGIN SELECT RAISE(ABORT,'VERIFICATION_STAGE_NOT_READY'); END;

CREATE TRIGGER "code_step_registration" BEFORE INSERT ON "code_operation_steps"
WHEN NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.operation_id AND ((o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=1 AND NEW.step_type='RESTORE_WORKSPACE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=2 AND NEW.step_type='PREPARE_BASIS') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=3 AND NEW.step_type='CHECK_CONDITIONS') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=4 AND NEW.step_type='START_INSTANCE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=5 AND NEW.step_type='CREATE_SESSION') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='START' AND NEW.step_no=6 AND NEW.step_type='SEND_INITIAL') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=1 AND NEW.step_type='RECONCILE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=2 AND NEW.step_type='CHECK_CONDITIONS') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=3 AND NEW.step_type='CONTINUE_OR_OBSERVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='ANSWER_QUESTION' AND NEW.step_no=1 AND NEW.step_type='READ_NATIVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='ANSWER_QUESTION' AND NEW.step_no=2 AND NEW.step_type='SEND_RESPONSE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='ANSWER_QUESTION' AND NEW.step_no=3 AND NEW.step_type='CONFIRM_NATIVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DECIDE_PERMISSION' AND NEW.step_no=1 AND NEW.step_type='READ_NATIVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DECIDE_PERMISSION' AND NEW.step_no=2 AND NEW.step_type='SEND_RESPONSE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DECIDE_PERMISSION' AND NEW.step_no=3 AND NEW.step_type='CONFIRM_NATIVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_HANDOFF' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_HANDOFF' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='APPLY_CONFIGURATION' AND NEW.step_no=1 AND NEW.step_type='BLOCK_NEW') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='APPLY_CONFIGURATION' AND NEW.step_no=2 AND NEW.step_type='QUIESCE_IF_REQUIRED') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='APPLY_CONFIGURATION' AND NEW.step_no=3 AND NEW.step_type='APPLY_PAIR') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='APPLY_CONFIGURATION' AND NEW.step_no=4 AND NEW.step_type='VERIFY_EFFECTIVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='VERIFY_CANDIDATE' AND NEW.step_no=1 AND NEW.step_type='CHECK_CONDITIONS') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='VERIFY_CANDIDATE' AND NEW.step_no=2 AND NEW.step_type='RESTORE_CHECK_COPY') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='VERIFY_CANDIDATE' AND NEW.step_no=3 AND NEW.step_type='CHECK') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='SUBMIT_FOR_TESTING' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='SUBMIT_FOR_TESTING' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='LINK_TEST_REPORT' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='LINK_TEST_REPORT' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='CAPTURE_AND_CHECK' AND NEW.step_no=1 AND NEW.step_type='QUIESCE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='CAPTURE_AND_CHECK' AND NEW.step_no=2 AND NEW.step_type='CAPTURE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='CAPTURE_AND_CHECK' AND NEW.step_no=3 AND NEW.step_type='PUBLISH') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='CAPTURE_AND_CHECK' AND NEW.step_no=4 AND NEW.step_type='CHECK') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='REPAIR' AND NEW.step_no=1 AND NEW.step_type='RESTORE_SOURCE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='REPAIR' AND NEW.step_no=2 AND NEW.step_type='SEND_REPAIR') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='REPAIR' AND NEW.step_no=3 AND NEW.step_type='OBSERVE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='REPAIR' AND NEW.step_no=4 AND NEW.step_type='CAPTURE_RESULT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='HANDOFF_ROLE' AND NEW.step_no=1 AND NEW.step_type='QUIESCE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='HANDOFF_ROLE' AND NEW.step_no=2 AND NEW.step_type='REVOKE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='HANDOFF_ROLE' AND NEW.step_no=3 AND NEW.step_type='CHECK') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='HANDOFF_ROLE' AND NEW.step_no=4 AND NEW.step_type='CREATE_SESSION') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='HANDOFF_ROLE' AND NEW.step_no=5 AND NEW.step_type='SEND_HANDOFF') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_DELIVERY' AND NEW.step_no=1 AND NEW.step_type='VALIDATE_REPORT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_DELIVERY' AND NEW.step_no=2 AND NEW.step_type='READ_TARGET') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_DELIVERY' AND NEW.step_no=3 AND NEW.step_type='SEAL_TARGET') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='PREPARE_DELIVERY' AND NEW.step_no=4 AND NEW.step_type='SAVE_PLAN') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=1 AND NEW.step_type='FIX_COMMIT_INPUT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=2 AND NEW.step_type='BUILD_OBJECTS') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=3 AND NEW.step_type='SAVE_PLANNED_COMMIT') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=4 AND NEW.step_type='PREPARE_REF') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=5 AND NEW.step_type='VERIFY_LOCKED_TARGET') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=6 AND NEW.step_type='DISPATCH_COMMIT_ONCE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=7 AND NEW.step_type='RECONCILE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='DELIVER' AND NEW.step_no=8 AND NEW.step_type='FINALIZE_OWNED_RUNTIME') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=1 AND NEW.step_type='BLOCK_NEW') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=2 AND NEW.step_type='REVOKE_GATEWAY') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=3 AND NEW.step_type='ABORT_IF_APPLICABLE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=4 AND NEW.step_type='STOP_OWNED_ACTIVITY') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=5 AND NEW.step_type='RECONCILE_WRITES') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=6 AND NEW.step_type='CLEANUP') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=1 AND NEW.step_type='QUERY') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=2 AND NEW.step_type='COMPARE') OR (o.task_id IS NOT NULL AND o.testing_task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=3 AND NEW.step_type='RECORD') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND NEW.step_no=1 AND NEW.step_type='BUILD_CONTEXT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND NEW.step_no=2 AND NEW.step_type='RESERVE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND NEW.step_no=3 AND NEW.step_type='CALL_MODEL') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND NEW.step_no=4 AND NEW.step_type='SAVE_DRAFT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE_PLAN') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=2 AND NEW.step_type='COMPILE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=3 AND NEW.step_type='SEAL') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=4 AND NEW.step_type='SAVE_PACK') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=1 AND NEW.step_type='FIX_REFERENCE_SET') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=2 AND NEW.step_type='CREATE_CHILD_TASKS') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=3 AND NEW.step_type='OBSERVE_CHILDREN') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=4 AND NEW.step_type='SAVE_VALIDATION') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=1 AND NEW.step_type='FIX_INPUT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=2 AND NEW.step_type='MATERIALIZE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=3 AND NEW.step_type='PREPARE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=4 AND NEW.step_type='EXECUTE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=5 AND NEW.step_type='STOP') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=6 AND NEW.step_type='VERIFY_INPUT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=7 AND NEW.step_type='CLEANUP') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RUN_TEST' AND NEW.step_no=8 AND NEW.step_type='SAVE_REPORT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=1 AND NEW.step_type='FENCE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=2 AND NEW.step_type='STOP_OWN_ACTIVITIES') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=3 AND NEW.step_type='VERIFY_STOP') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=4 AND NEW.step_type='CLEANUP') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE' AND NEW.step_no=5 AND NEW.step_type='SAVE_TERMINATED') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=1 AND NEW.step_type='RECONCILE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=2 AND NEW.step_type='CHECK_CONDITIONS') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RESUME' AND NEW.step_no=3 AND NEW.step_type='CONTINUE_OR_OBSERVE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=1 AND NEW.step_type='QUERY') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=2 AND NEW.step_type='COMPARE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='RECONCILE' AND NEW.step_no=3 AND NEW.step_type='RECORD') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='ATTACH_ASSETS' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='ATTACH_ASSETS' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='INCREASE_TEST_BUDGET' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='INCREASE_TEST_BUDGET' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVIEW_FINDING' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVIEW_FINDING' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='PUBLISH_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='PUBLISH_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='PUBLISH_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='PUBLISH_PACK' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVOKE_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVOKE_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVOKE_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='REVOKE_PACK' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_BASE' AND NEW.step_no=1 AND NEW.step_type='VALIDATE_COMMIT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_BASE' AND NEW.step_no=2 AND NEW.step_type='PIN_COMMIT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_BASE' AND NEW.step_no=3 AND NEW.step_type='VERIFY_PINNED_OBJECTS') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_BASE' AND NEW.step_no=4 AND NEW.step_type='SAVE_BASELINE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REFRESH_REPOSITORY' AND NEW.step_no=1 AND NEW.step_type='READ_REPOSITORY') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REFRESH_REPOSITORY' AND NEW.step_no=2 AND NEW.step_type='SAVE_OBSERVATION') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_REPOSITORY' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REGISTER_REPOSITORY' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_EXECUTION_PROFILE' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_EXECUTION_PROFILE' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_CHECK_SET' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_CHECK_SET' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_EXECUTION_PROFILE' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_EXECUTION_PROFILE' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_CHECK_SET' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_CHECK_SET' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='APPROVE_AUTHORIZATION' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='APPROVE_AUTHORIZATION' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='CREATE_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='EDIT_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='EDIT_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVOKE_PLAN' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVOKE_PLAN' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE_PLAN') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=2 AND NEW.step_type='COMPILE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=3 AND NEW.step_type='SEAL') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='SEAL_PACK' AND NEW.step_no=4 AND NEW.step_type='SAVE_PACK') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='PUBLISH_PACK' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVOKE_PACK' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVOKE_PACK' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVIEW_FINDING' AND NEW.step_no=1 AND NEW.step_type='VALIDATE') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='REVIEW_FINDING' AND NEW.step_no=2 AND NEW.step_type='SAVE_FACT') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=1 AND NEW.step_type='FIX_REFERENCE_SET') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=2 AND NEW.step_type='CREATE_CHILD_TASKS') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=3 AND NEW.step_type='OBSERVE_CHILDREN') OR (o.task_id IS NULL AND o.testing_task_id IS NULL AND o.operation_type='VALIDATE_PACK' AND NEW.step_no=4 AND NEW.step_type='SAVE_VALIDATION'))) OR (NEW.step_no>1 AND NOT EXISTS(SELECT 1 FROM code_operation_steps p WHERE p.operation_id=NEW.operation_id AND p.step_no=NEW.step_no-1))
BEGIN SELECT RAISE(ABORT,'UNREGISTERED_OPERATION_STEP'); END;
