# `backend/personal_fields_are_declared`

**A model field named like personal data says whether it holds personal data**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/personal_fields_are_declared.json`.

## Why this rule exists

Personal data has no shape a redactor can find: an email address, a phone number or a date of birth is a string or a date like every other value, so a log, an audit trail or an event payload that leaves the process can withhold it only where the model holding it says which of its fields are personal. That declaration is made per field and per model, because a data-transfer model that redeclares a field without it has declared that field not personal, and a reader of the redeclaring model has nothing else to go on. So a field whose name says it holds a person's data is either declared personal on every model that declares it, or carries a justified opt-out stating why it holds no person's data (an organisation's shared mailbox is not a person's address). The name test is a fixed vocabulary matched against the last words of the field name, case-insensitively, at an underscore boundary: an email address (email, e_mail, emails, email_address, email_addresses), a phone number (phone, phones, phone_number, phone_numbers, telephone, telephone_number, mobile_number), a date of birth (date_of_birth, birth_date, birthdate, birthday, dob), a national identifier (national_id, national_id_number, national_identification_number, national_identity_number, social_security_number, ssn, bsn, passport_number), a person's name (first_name, last_name, full_name, given_name, family_name, middle_name, surname) and a home address (home_address, residential_address). So contact_email is in scope and email_verified is not: a flag about an address is not the address. The vocabulary is deliberately short, names that hold a person's data in nearly every application, and it is a floor rather than a definition of personal data: a postcode, a bare address or a bare name belongs to an organisation as often as to a person, and declaring those is left to the author. Only model classes are in scope: a persisted table, or a data-transfer or validation model, directly or through a model base defined in the same tree. A plain class, a record type that cannot carry the field declaration, and a function parameter are not.

## How Terp realises this

terp.core.Personal(...) declares the field: it is sqlmodel's Field with every keyword forwarded, and it records the declaration in the field's metadata (personal_fields(Model)) and in a table column's info (personal_columns()), so no DDL, JSON schema or OpenAPI document changes and no migration follows. What reads it: the log renders a declared field as [PERSONAL] in any model it is handed and withholds a value logged under a declared field's name; the audit trail keeps the key and drops the value; a model with a declared field hides its input in a validation error's text; a PUBLIC event or job may not declare one in its payload; redact_personal(payload) is the copy that may leave the process. The check accepts Personal(...) as the field's value or inside Annotated[...]; a class is a model when it is a table=True class or its bases reach SQLModel, BaseModel, BaseTable, BaseSchema or BaseUpdateSchema by name through the scanned tree. The three checks that read a field's keywords (input_str_fields_have_max_length, no_unique_columns_on_soft_delete_models, references_declare_delete_behaviour) read Personal as they read Field. Recipe: terp guide personal-data (ADR 0190).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-personal-fields-are-declared: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a model whose base comes from another package under a name that is not one of the known model bases (a third-party base model) is not required to be recognised as a model, because the check resolves bases by name within the scanned tree
- a model built at runtime (create_model, a class assembled by a factory) is not required to be read: its fields exist only once the code runs

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_personal_fields_are_declared`
