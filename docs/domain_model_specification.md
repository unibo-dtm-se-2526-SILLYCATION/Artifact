# Domain Model Specification

**Project:** Sillycation  
**Based on:** Requirements Specification v1.0

---

## 1. Domain Overview

Sillycation is a trip-based application in which registered users create trips, join them as participants, record memorable episodes, vote on those episodes, and obtain a final participant ranking.

The domain model is designed according to Domain-Driven Design (DDD) principles.

The core domain concepts are:

- User
- Trip
- Participant
- JoinRequest
- Episode
- Vote

The domain also contains value objects representing concepts such as:

- TripId
- UserId
- EpisodeId
- InvitationCode
- TripPeriod
- VoteValue

The model must preserve the business rules and domain invariants defined in the Requirements Specification.

---

## 2. Bounded Contexts

The Sillycation domain is divided into four bounded contexts.

### 2.1 Identity and Access Context

#### Responsibility

This context manages the identity of registered users and authentication.

It is responsible for:

- user registration;
- unique username and email;
- authentication;
- user identity.

#### Main Domain Concepts

- User
- UserId

Authentication mechanisms such as JWT belong to the application/infrastructure layers and are not part of the core domain model.

The domain only needs a reliable identity (`UserId`) to determine which user is performing an operation.

---

### 2.2 Trip Management Context

#### Responsibility

This context manages the lifecycle and membership of a trip.

It is responsible for:

- trip creation;
- trip dates;
- trip creator;
- invitation code;
- join requests;
- participant membership;
- trip lifecycle;
- trip completion;
- trip archival.

#### Main Domain Concepts

- Trip
- Participant
- JoinRequest
- InvitationCode
- TripPeriod
- TripStatus

#### Trip Lifecycle

```text
PLANNED
   |
   v
ACTIVE
   |
   v
COMPLETED
   |
   v
ARCHIVED
```

Backward transitions and skipped transitions are not allowed.

---

### 2.3 Episode and Voting Context

#### Responsibility

This context manages memorable episodes and their voting process.

It is responsible for:

- episode creation;
- episode modification while in draft;
- episode submission;
- voting;
- voting eligibility;
- automatic episode completion;
- episode score calculation.

#### Main Domain Concepts

- Episode
- Vote
- VoteValue
- EpisodeStatus

#### Episode Lifecycle

```text
DRAFT
   |
   v
SUBMITTED
   |
   v
VOTING
   |
   v
COMPLETED
```

The transition from `SUBMITTED` to `VOTING` occurs automatically as part of the episode submission workflow.

---

### 2.4 Ranking Context

#### Responsibility

This context calculates the ranking of trip participants from completed episodes.

It is responsible for:

- episode score calculation;
- participant total score calculation;
- ranking ordering;
- tie handling;
- identification of the trip loser or co-losers.

Only completed episodes contribute to the ranking.

The participant with the highest total score is considered the trip loser. Participants with the same score share the same ranking position using competition ranking.

---

## 3. Entities

An Entity is a domain object that has a unique identity and can change over time while remaining the same conceptual object.

The main Sillycation entities are:

| Entity | Identity | Main Responsibility |
|---|---|---|
| User | UserId | Represents a registered Sillycation user |
| Trip | TripId | Controls trip lifecycle and membership |
| Participant | UserId + TripId | Represents the membership of a user in a trip |
| JoinRequest | JoinRequestId | Represents a pending request to join a trip |
| Episode | EpisodeId | Controls an episode and its lifecycle |
| Vote | VoteId | Represents the vote of one participant on one episode |

---

## 4. User Entity

### Identity

```text
UserId
```

### Main Attributes

```text
User
├── id: UserId
├── username
├── email
└── password_hash
```

The password itself must never be stored in plain text.

### Responsibilities

The User entity represents a registered user of Sillycation.

Trip-specific roles are not stored as permanent roles of the User.

A User may be:

- creator of one Trip;
- participant of another Trip;
- both creator and participant of different Trips.

Therefore, `Trip Creator` and `Participant` are trip-specific concepts rather than global user roles.

---

## 5. Trip Aggregate

### 5.1 Aggregate Root

`Trip` is an **Aggregate Root**.

It controls the consistency of the trip and protects the rules concerning:

- creator;
- membership;
- trip lifecycle;
- trip period;
- invitation code;
- join requests.

External objects should not directly modify the internal state of the Trip aggregate.

Changes must occur through operations exposed by the Trip Aggregate Root.

### 5.2 Trip Structure

```text
Trip
├── id: TripId
├── name
├── description
├── creatorId: UserId
├── period: TripPeriod
├── status: TripStatus
├── invitationCode: InvitationCode
├── participants
└── joinRequests
```

### 5.3 TripStatus

```text
TripStatus
├── PLANNED
├── ACTIVE
├── COMPLETED
└── ARCHIVED
```

### 5.4 Trip Behaviour

Conceptually, the Trip Aggregate Root exposes operations such as:

```text
createTrip(...)
requestToJoin(...)
approveJoinRequest(...)
rejectJoinRequest(...)
activate(...)
complete(...)
archive(...)
```

These operations must protect the Trip invariants rather than allowing arbitrary modification of Trip attributes.

For example, the application should not directly execute:

```text
trip.status = ACTIVE
```

Instead, it should request the domain operation:

```text
trip.activate(...)
```

The Trip domain logic then determines whether the transition is valid.

---

## 6. Participant Entity

A Participant represents the membership of a User in a specific Trip.

It is not a separate registered identity.

Conceptually:

```text
Participant
├── tripId: TripId
└── userId: UserId
```

The Trip Creator automatically becomes a Participant when the Trip is created.

A User becomes a Participant of another Trip only after the corresponding join request has been approved.

Participant membership becomes immutable when the Trip becomes `ACTIVE`.

---

## 7. JoinRequest Entity

The requirements define a pending join request created when an authenticated user submits a valid Trip invitation code.

Therefore, the domain model represents this concept explicitly as `JoinRequest`.

```text
JoinRequest
├── id: JoinRequestId
├── tripId: TripId
├── userId: UserId
└── status
```

Possible states are conceptually:

```text
PENDING
APPROVED
REJECTED
```

A JoinRequest can be created only while the Trip is `PLANNED`.

Only the Trip Creator can approve or reject it.

Approval makes the requesting User a Participant.

A duplicate pending request from the same User for the same Trip is not allowed.

---

## 8. InvitationCode Value Object

The invitation mechanism does not need to be modelled as an independent `Invitation` entity because the requirements define a unique invitation code associated with each Trip rather than an invitation with an independent lifecycle.

Therefore, `InvitationCode` is modelled as a **Value Object**.

```text
InvitationCode
└── value
```

Properties:

- generated by the system;
- unique for each Trip;
- immutable;
- associated with one Trip;
- usable to request access only while the Trip is `PLANNED`.

The code identifies the Trip but does not automatically make a User a Participant.

Submitting it creates a `JoinRequest`.

---

## 9. Episode Aggregate

### 9.1 Aggregate Root

`Episode` is an **Aggregate Root**.

It controls:

- episode information;
- episode lifecycle;
- author;
- protagonist;
- votes;
- voting eligibility;
- automatic completion;
- final episode score.

### 9.2 Episode Structure

```text
Episode
├── id: EpisodeId
├── tripId: TripId
├── authorId: UserId
├── protagonistId: UserId
├── title
├── description
├── date
├── pictureReference (FR-23 stretch extension only; excluded from MVP)
├── status: EpisodeStatus
└── votes
```

The author and protagonist may be different Participants.

### 9.3 EpisodeStatus

```text
EpisodeStatus
├── DRAFT
├── SUBMITTED
├── VOTING
└── COMPLETED
```

### 9.4 Episode Behaviour

Conceptually, the Episode Aggregate Root exposes operations such as:

```text
create(...)
edit(...)
delete(...)
submit(...)
castVote(...)
complete(...)
calculateScore(...)
```

The Episode Aggregate Root must protect its own lifecycle.

For example, editing is allowed only when:

```text
episode.status == DRAFT
AND
requesting_user == episode.author
```

Voting is allowed only when:

```text
episode.status == VOTING
```

---

## 10. Vote Entity

A Vote represents the rating assigned by one eligible Participant to one Episode.

```text
Vote
├── id: VoteId
├── episodeId: EpisodeId
├── voterId: UserId
└── value: VoteValue
```

A Vote has identity because the system must distinguish individual submitted votes and enforce the rule that a Participant can vote at most once on the same Episode.

Once submitted, a Vote is immutable.

It cannot be edited or deleted.

---

## 11. VoteValue Value Object

The numerical value of a Vote is represented by a Value Object.

```text
VoteValue
└── value: integer
```

Invariant:

```text
1 <= value <= 5
```

A `VoteValue` cannot exist with an invalid value.

Examples:

```text
VoteValue(1)   -> valid
VoteValue(3)   -> valid
VoteValue(5)   -> valid

VoteValue(0)   -> invalid
VoteValue(6)   -> invalid
VoteValue(2.5) -> invalid
```

This ensures that invalid voting values cannot enter the domain model.

---

## 12. TripPeriod Value Object

The Trip date interval is represented as a Value Object.

```text
TripPeriod
├── startDate
└── endDate
```

Invariant:

```text
startDate <= endDate
```

A `TripPeriod` with an invalid date interval cannot be created.

The value object can also provide the domain operation:

```text
overlaps(otherTripPeriod)
```

Two Trip periods overlap when:

```text
newTrip.startDate <= existingTrip.endDate
AND
newTrip.endDate >= existingTrip.startDate
```

This rule is required when creating a Trip, requesting to join a Trip, and approving a JoinRequest.

---

## 13. Identifier Value Objects

Domain identifiers should be represented explicitly rather than using unstructured primitive values throughout the domain.

Examples:

```text
UserId
TripId
EpisodeId
JoinRequestId
VoteId
```

These Value Objects prevent identifiers belonging to different domain concepts from being confused.

For example, a `TripId` and an `EpisodeId` are conceptually different even if both are technically stored as strings or UUIDs.

---

## 14. Aggregate Roots

The principal Aggregate Roots are:

| Aggregate Root | Contains / Controls | Main Invariants |
|---|---|---|
| Trip | Participants, JoinRequests, InvitationCode, TripPeriod | membership and Trip lifecycle |
| Episode | Votes, VoteValue | Episode lifecycle and voting |

`User` has its own identity and lifecycle and is managed independently by the Identity and Access Context.

The Trip does not directly contain all Episode objects as part of the same aggregate.

Episodes reference their Trip through `TripId`.

This keeps the Trip aggregate smaller and avoids requiring the entire Trip, all Episodes, and all Votes to be loaded whenever one Episode receives a vote.

---

## 15. Repository Interfaces

Repositories provide access to persisted domain objects without making the domain depend on SQLAlchemy, SQLite, or another database technology.

Repository interfaces belong to the domain/application boundary.

Concrete implementations belong to the infrastructure layer.

### 15.1 UserRepository

```text
UserRepository

save(user)
getById(userId)
getByUsername(username)
getByEmail(email)
existsByUsername(username)
existsByEmail(email)
```

Used for registration and user lookup.

### 15.2 TripRepository

```text
TripRepository

save(trip)
getById(tripId)
getByInvitationCode(invitationCode)
findByParticipant(userId)
findActiveOrPlannedTripsByParticipant(userId)
```

It allows the application/domain logic to retrieve the Trips necessary to enforce membership and overlapping-date rules.

### 15.3 EpisodeRepository

```text
EpisodeRepository

save(episode)
getById(episodeId)
findByTrip(tripId)
findUnresolvedByTrip(tripId)
```

`findUnresolvedByTrip` supports Trip completion by determining whether `DRAFT`, `SUBMITTED`, or `VOTING` Episodes still exist.

### 15.4 Repository Abstraction

The domain must depend only on abstractions such as:

```text
TripRepository
EpisodeRepository
UserRepository
```

and not directly on:

```text
SQLAlchemy
SQLite
database tables
FastAPI
```

Conceptually:

```text
DOMAIN
   |
   v
Repository Interface
   ^
   |
INFRASTRUCTURE
   |
SQLAlchemy implementation
   |
SQLite / relational database
```

This preserves the separation required by Hexagonal Architecture.

---

## 16. Domain Services

Domain Services are introduced only when a domain operation does not naturally belong to a single Entity or Value Object.

The following services are useful in Sillycation.

### 16.1 TripConflictService

#### Responsibility

Determines whether a User can participate in a Trip without violating the non-overlapping Trip rule.

Conceptually:

```text
hasTripConflict(userId, tripPeriod)
```

The service checks the User's existing `PLANNED` and `ACTIVE` Trips.

The operation is required during:

```text
Create Trip
Request to Join Trip
Approve Join Request
```

The check must be repeated during approval because the applicant may have joined another conflicting Trip after submitting the JoinRequest.

This logic cannot be evaluated by a single Trip alone because it requires knowledge of other Trips in which the User participates.

### 16.2 RankingService

#### Responsibility

Calculates the ranking from completed Episodes.

For each completed Episode:

```text
episode_score =
    sum(valid votes) / number_of_votes
```

For each Participant:

```text
participant_score =
    sum(score of each COMPLETED episode
        where participant is protagonist)
```

Only `COMPLETED` Episodes contribute.

Participants are ordered by descending total score.

Participants with identical scores share the same position using competition ranking.

Example:

```text
Anna   20 -> position 1
Luca   17 -> position 2
Marco  17 -> position 2
Sara   10 -> position 4
```

The Participant or Participants in first place are identified as the Trip loser or co-losers.

---

## 17. Factories

Factories should be introduced only when object creation requires domain rules that would otherwise make construction unclear or inconsistent.

For the initial Sillycation domain, only a small number of creation operations need factory-like behaviour.

### 17.1 Trip Creation

Creating a Trip requires:

```text
TripId
name
creatorId
TripPeriod
optional description
InvitationCode
```

The creation process must guarantee:

```text
status = PLANNED
creator is also Participant
unique InvitationCode exists
valid TripPeriod exists
```

This can be implemented through a `Trip.create(...)` factory method or, if needed, a dedicated `TripFactory`.

A separate factory is not necessary unless creation becomes more complex.

### 17.2 Episode Creation

An Episode creation operation must guarantee:

```text
status = DRAFT
author belongs to Trip
protagonist belongs to Trip
episode date belongs to TripPeriod
Trip status = ACTIVE
```

This may be implemented through an `Episode.create(...)` factory method.

Again, a separate `EpisodeFactory` should only be introduced if creation logic becomes sufficiently complex.

---

## 18. Domain Invariants

The domain model must enforce the invariants defined in the Requirements Specification.

### Trip Invariants

```text
INV-01
A Trip always has exactly one creator.

INV-02
The Trip creator is always also a Trip participant.

INV-03
A Trip start date cannot be later than its end date.

INV-04
A User cannot participate in two PLANNED or ACTIVE Trips whose date intervals overlap.

INV-05
Trip membership cannot change after the Trip becomes ACTIVE.

INV-06
A Trip can become ACTIVE only on or after its start date and with at least two participants.

INV-17
A Trip cannot become COMPLETED before its end date.

INV-18
A Trip cannot become COMPLETED while unresolved Episodes exist.

INV-19
A COMPLETED Trip cannot receive new Participants, Episodes, or Votes.

INV-20
An ARCHIVED Trip is read-only.

INV-21
Trip lifecycle transitions cannot move backwards or skip states.
```

### Episode Invariants

```text
INV-07
A protagonist must belong to the same Trip as the Episode.

INV-08
An Episode can be created only while its Trip is ACTIVE.

INV-09
An Episode can receive votes only while its state is VOTING.

INV-14
A SUBMITTED, VOTING, or COMPLETED Episode cannot be edited or deleted.

INV-15
An Episode becomes COMPLETED when every eligible voter has voted.
```

### Vote Invariants

```text
INV-10
A protagonist cannot vote on their own Episode.

INV-11
A Participant can vote at most once on the same Episode.

INV-12
A Vote must be an integer in [1, 5].

INV-13
A submitted Vote cannot be modified or deleted.
```

### Ranking Invariants

```text
INV-16
Only COMPLETED Episodes contribute to the Participant ranking.

INV-22
Participants with the same ranking score share the same position.

INV-23
The Participant or Participants with the highest final score are the Trip loser(s).
```

---

## 19. Invariant Ownership

Each invariant should have a clear owner in the domain model.

| Invariant | Primary Owner |
|---|---|
| INV-01 | Trip |
| INV-02 | Trip |
| INV-03 | TripPeriod |
| INV-04 | TripConflictService |
| INV-05 | Trip |
| INV-06 | Trip |
| INV-07 | Episode creation/application coordination |
| INV-08 | Episode creation/application coordination |
| INV-09 | Episode |
| INV-10 | Episode |
| INV-11 | Episode |
| INV-12 | VoteValue |
| INV-13 | Vote |
| INV-14 | Episode |
| INV-15 | Episode |
| INV-16 | RankingService |
| INV-17 | Trip |
| INV-18 | Trip completion/application coordination |
| INV-19 | Trip + application coordination |
| INV-20 | Trip |
| INV-21 | Trip |
| INV-22 | RankingService |
| INV-23 | RankingService |

Some invariants require information belonging to more than one Aggregate.

For example, an Episode cannot independently know whether its protagonist is currently a Participant of the corresponding Trip unless the relevant Trip information is provided to it.

In these cases, the application layer loads the required Aggregates and coordinates the operation, while the domain model remains responsible for the actual business rule.

---

## 20. Cross-Aggregate Rules

Some Sillycation rules cannot be enforced using only one Aggregate.

### 20.1 User Trip Overlap

To determine whether a User may create or join a Trip, the system must inspect other Trips in which the User participates.

Therefore:

```text
Application Service
      |
      v
TripRepository
      |
      v
existing PLANNED / ACTIVE Trips
      |
      v
TripConflictService
      |
      v
allow / reject
```

### 20.2 Episode Creation

Creating an Episode requires information from both the Trip and the new Episode.

The application must verify:

```text
Trip.status == ACTIVE
author is Participant
protagonist is Participant
episode.date is within TripPeriod
```

After these conditions are satisfied, the Episode can be created.

### 20.3 Trip Completion

Completing a Trip requires both Trip information and Episode information.

The application retrieves unresolved Episodes through the EpisodeRepository.

The transition is allowed only when:

```text
Trip.status == ACTIVE
AND
current_date >= Trip.endDate
AND
no DRAFT Episodes exist
AND
no SUBMITTED Episodes exist
AND
no VOTING Episodes exist
```

The Trip Creator must explicitly request the transition.

Reaching `endDate` does not automatically complete the Trip.

This allows the Trip to remain `ACTIVE` after its official end date so that Participants may still add and resolve Episodes before the Creator closes the game.

---

## 21. Voting Eligibility

The eligible voters of an Episode are all Participants whose membership was locked when the Trip became `ACTIVE`, except the Episode protagonist.

Formally:

```text
eligible_voters =
    trip.participants - {episode.protagonist}
```

Therefore:

```text
expected_votes =
    number_of_trip_participants - 1
```

When every eligible voter has submitted exactly one Vote:

```text
Episode.status -> COMPLETED
```

No additional Vote is accepted afterward.

---

## 22. Domain Relationships

The main domain relationships are:

```text
User
 │
 │ creates
 ▼
Trip
 │
 ├──── has ────> Participant
 │
 ├──── has ────> JoinRequest
 │
 └──── identified for joining by ────> InvitationCode

Trip
 │
 │ contains
 ▼
Episode
 │
 ├──── authored by ────> Participant
 │
 ├──── protagonist ────> Participant
 │
 └──── contains ────> Vote
                         │
                         └──── cast by ────> Participant
```

The same User may participate in multiple Trips, provided that the date intervals of `PLANNED` or `ACTIVE` Trips do not overlap.

---

## 23. Domain Model Summary

The resulting DDD model is:

```text
IDENTITY AND ACCESS CONTEXT
│
└── User
    └── UserId


TRIP MANAGEMENT CONTEXT
│
├── Trip                         [Aggregate Root]
│   ├── Participant              [Entity]
│   ├── JoinRequest              [Entity]
│   ├── TripPeriod               [Value Object]
│   ├── InvitationCode           [Value Object]
│   └── TripStatus
│
├── TripRepository               [Repository Interface]
└── TripConflictService          [Domain Service]


EPISODE AND VOTING CONTEXT
│
├── Episode                      [Aggregate Root]
│   ├── Vote                     [Entity]
│   │   └── VoteValue            [Value Object]
│   └── EpisodeStatus
│
└── EpisodeRepository            [Repository Interface]


RANKING CONTEXT
│
└── RankingService               [Domain Service]
```

The domain model does not depend directly on:

```text
FastAPI
SQLAlchemy
SQLite
JWT
frontend framework
Docker
```

These technologies belong to the application, infrastructure, API, or deployment layers.

This separation keeps the core business rules independent from technical implementation details and supports the Hexagonal Architecture required by the project.
