import uuid
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


HAND_LIMIT = 5


@dataclass
class Card:
    id: str
    name: str
    type: str  # "resource", "building", "attack", "special"
    image: str
    cost: Dict[str, int] = field(default_factory=dict)  # for buildings
    effect: Optional[str] = None  # e.g. "riot", "fire", "defense", etc.


class Game:
    """
    Game state for a single room.
    All data is kept in memory for demo purposes.
    """

    def __init__(self, room_code: str):
        self.room_code = room_code
        self.players: Dict[str, Dict[str, Any]] = {}  # player_id -> {...}
        self.turn_order: List[str] = []
        self.current_player_index: int = 0

        self.deck: List[Card] = []
        self.discard_pile: List[Card] = []
        self.reshuffle_count: int = 0

        self._build_deck()
        self._shuffle_deck()

    # -------------------------------------------------------------------------
    # Deck & cards
    # -------------------------------------------------------------------------

    def _build_deck(self) -> None:
        """
        Build the full deck according to the card definitions.
        Images assume files in assets/cards/*.png
        """

        self.deck = []

        # --- Resource cards ---------------------------------------------------
        def add_resource(name: str, image: str, count: int, resource_key: str):
            for _ in range(count):
                self.deck.append(
                    Card(
                        id=str(uuid.uuid4()),
                        name=name,
                        type="resource",
                        image=image,
                        cost={"resource": resource_key},  # stored type for convenience
                    )
                )

        # As per spec:
        # Akmens 7, Koks 7, Zināšanas 6, Zelts 5
        add_resource("Akmens", "akmens.png", 7, "stone")
        add_resource("Koks", "koks.png", 7, "wood")
        add_resource("Zināšanas", "zināšanas.png", 6, "knowledge")
        add_resource("Zelts", "zelts.png", 5, "gold")

        # --- Building cards ---------------------------------------------------
        def add_building(name: str, image: str, count: int, cost: Dict[str, int]):
            for _ in range(count):
                self.deck.append(
                    Card(
                        id=str(uuid.uuid4()),
                        name=name,
                        type="building",
                        image=image,
                        cost=cost,
                    )
                )

        # Costs are in resource keys: stone, wood, knowledge, gold
        add_building("Mūris", "mūris.png", 3, {"stone": 1})
        add_building("Tilts", "tilts.png", 3, {"stone": 1, "knowledge": 1})
        add_building("Tornis", "tornis.png", 3, {"stone": 1, "wood": 1})
        add_building("Bibliotēka", "bibliotēka.png", 3, {"knowledge": 1, "wood": 1})
        add_building("Lielā zāle", "lielā_zāle.png", 3, {"stone": 1, "gold": 1, "wood": 1})
        add_building(
            "Tirgus laukums",
            "tirgus_laukums.png",
            2,
            {"gold": 1, "knowledge": 1, "wood": 1},
        )
        add_building(
            "Pils",
            "pils.png",
            2,
            {"stone": 1, "knowledge": 1, "wood": 1, "gold": 1},
        )

        # --- Attack cards -----------------------------------------------------
        # Spec does not give quantities; we assume 4 each for demo.
        def add_attack(name: str, image: str, effect: str, count: int = 4):
            for _ in range(count):
                self.deck.append(
                    Card(
                        id=str(uuid.uuid4()),
                        name=name,
                        type="attack",
                        image=image,
                        effect=effect,
                    )
                )

        add_attack("Nemieri", "nemieri.png", "riot", count=4)
        add_attack("Ugunsgrēks", "ugunsgrēks.png", "fire", count=4)

        # --- Special cards ----------------------------------------------------
        # Spec does not give quantities; we assume 3 of each for demo.
        def add_special(name: str, image: str, effect: str, count: int = 3):
            for _ in range(count):
                self.deck.append(
                    Card(
                        id=str(uuid.uuid4()),
                        name=name,
                        type="special",
                        image=image,
                        effect=effect,
                    )
                )

        add_special("Aizsardzība", "aizsardzība.png", "defense", count=3)
        add_special("Apmaiņa", "apmaiņa.png", "swap_resource", count=3)
        add_special("Slepenais darījums", "slepenais_darījums.png", "steal_card", count=3)
        add_special("Pārņemšana", "pārņemšana.png", "takeover", count=2)

    def _shuffle_deck(self) -> None:
        random.shuffle(self.deck)

    def _reshuffle_if_needed(self) -> None:
        """
        If deck is empty and we need cards, reshuffle discard pile into deck.
        Handles the rule: after 3 reshuffles, remove_takeover from game.
        """
        if self.deck:
            return

        if not self.discard_pile:
            # nothing to reshuffle
            return

        self.deck = self.discard_pile
        self.discard_pile = []
        self._shuffle_deck()
        self.reshuffle_count += 1

        # After 3 reshuffles, remove all "Pārņemšana" from the game.
        if self.reshuffle_count >= 3:
            self.deck = [c for c in self.deck if c.effect != "takeover"]
            self.discard_pile = [c for c in self.discard_pile if c.effect != "takeover"]

    def draw_card(self) -> Optional[Card]:
        """
        Draw a single card from deck. Reshuffle if needed.
        """
        if not self.deck:
            self._reshuffle_if_needed()
        if not self.deck:
            return None
        return self.deck.pop()

    # -------------------------------------------------------------------------
    # Players
    # -------------------------------------------------------------------------

    def add_player(self, name: str, sid: str) -> str:
        player_id = str(uuid.uuid4())
        self.players[player_id] = {
            "id": player_id,
            "sid": sid,  # Socket.IO session id
            "name": name,
            "hand": [],  # list[Card]
            "resources": {
                "stone": 0,
                "wood": 0,
                "knowledge": 0,
                "gold": 0,
            },
            "buildings": [],  # list[Card]
            "points": 0,
            "has_defense": False,
        }
        self.turn_order.append(player_id)
        return player_id

    def remove_player_by_sid(self, sid: str) -> Optional[str]:
        """
        Remove player when they disconnect. Return player_id if removed.
        """
        to_remove = None
        for pid, pdata in self.players.items():
            if pdata.get("sid") == sid:
                to_remove = pid
                break
        if not to_remove:
            return None

        # Put player's cards into discard pile
        pdata = self.players[to_remove]
        self.discard_pile.extend(pdata["hand"])
        self.discard_pile.extend(pdata["buildings"])
        del self.players[to_remove]
        if to_remove in self.turn_order:
            self.turn_order.remove(to_remove)
        return to_remove

    # -------------------------------------------------------------------------
    # Card / hand operations
    # -------------------------------------------------------------------------

    def deal_initial_hand(self, player_id: str) -> None:
        self.draw_up_to_hand_limit(player_id)

    def draw_up_to_hand_limit(self, player_id: str) -> None:
        player = self.players[player_id]
        while len(player["hand"]) < HAND_LIMIT:
            card = self.draw_card()
            if not card:
                break
            player["hand"].append(card)

    def play_card(
        self,
        player_id: str,
        card_id: str,
        target_player_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Play a card from the player's hand.
        Returns a dict with info or error, e.g. {"ok": True} or {"ok": False, "error": "..."}
        """
        player = self.players[player_id]
        card = next((c for c in player["hand"] if c.id == card_id), None)
        if not card:
            return {"ok": False, "error": "Card not found in hand"}

        # Remove from hand first, but keep reference
        player["hand"].remove(card)

        if card.type == "resource":
            return self._play_resource_card(player, card)

        if card.type == "building":
            return self._play_building_card(player, card)

        if card.type == "attack":
            return self._play_attack_card(player_id, card, target_player_id)

        if card.type == "special":
            return self._play_special_card(player_id, card, target_player_id, extra)

        # Unknown type -> discard
        self.discard_pile.append(card)
        return {"ok": True, "info": "Unknown card type, discarded."}

    def _play_resource_card(self, player: Dict[str, Any], card: Card) -> Dict[str, Any]:
        resource_key = card.cost.get("resource")
        if resource_key:
            player["resources"][resource_key] += 1
        # Resource stays on the table conceptually, but for simplicity we
        # just track counters; the card itself goes to discard.
        self.discard_pile.append(card)
        return {"ok": True}

    def _play_building_card(self, player: Dict[str, Any], card: Card) -> Dict[str, Any]:
        # Check cost
        for r, amount in card.cost.items():
            if player["resources"].get(r, 0) < amount:
                # Not enough resources -> return card to hand
                player["hand"].append(card)
                return {"ok": False, "error": "Not enough resources"}

        # Pay cost
        for r, amount in card.cost.items():
            player["resources"][r] -= amount

        # Place building on table
        player["buildings"].append(card)

        # Points according to spec
        points_map = {
            "Mūris": 1,
            "Tilts": 2,
            "Tornis": 2,
            "Bibliotēka": 2,
            "Tirgus laukums": 3,
            "Lielā zāle": 3,
            "Pils": 4,
        }
        player["points"] += points_map.get(card.name, 0)
        return {"ok": True}

    def _play_attack_card(
        self,
        player_id: str,
        card: Card,
        target_player_id: Optional[str],
    ) -> Dict[str, Any]:
        if not target_player_id or target_player_id not in self.players:
            # No valid target -> discard attack
            self.discard_pile.append(card)
            return {"ok": False, "error": "Invalid target"}

        target = self.players[target_player_id]

        # Check if target has defense flag
        if target.get("has_defense"):
            target["has_defense"] = False
            # defense used; attack discarded
            self.discard_pile.append(card)
            return {"ok": True, "info": "Attack canceled by defense"}

        if card.effect == "riot":
            # Destroy 1 resource: we remove from the first resource type that has > 0.
            for r in ["stone", "wood", "knowledge", "gold"]:
                if target["resources"][r] > 0:
                    target["resources"][r] -= 1
                    break

        elif card.effect == "fire":
            # Destroy 1 building (the last built, arbitrarily)
            if target["buildings"]:
                destroyed = target["buildings"].pop()
                # Return destroyed building to discard
                self.discard_pile.append(destroyed)

        # Attack card itself goes to discard
        self.discard_pile.append(card)
        return {"ok": True}

    def _play_special_card(
        self,
        player_id: str,
        card: Card,
        target_player_id: Optional[str],
        extra: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        player = self.players[player_id]

        if card.effect == "defense":
            player["has_defense"] = True
            self.discard_pile.append(card)
            return {"ok": True}

        if card.effect == "swap_resource":
            # Apmaiņa: for demo, we simply swap one random resource unit
            # between players if possible.
            if not target_player_id or target_player_id not in self.players:
                self.discard_pile.append(card)
                return {"ok": False, "error": "Invalid target for swap"}

            target = self.players[target_player_id]
            # Find any resource you have and any resource target has
            my_types = [r for r, v in player["resources"].items() if v > 0]
            target_types = [r for r, v in target["resources"].items() if v > 0]
            if not my_types or not target_types:
                self.discard_pile.append(card)
                return {"ok": False, "error": "No resources to swap"}

            my_r = random.choice(my_types)
            tg_r = random.choice(target_types)
            player["resources"][my_r] -= 1
            player["resources"][tg_r] += 1
            target["resources"][tg_r] -= 1
            target["resources"][my_r] += 1

            self.discard_pile.append(card)
            return {"ok": True}

        if card.effect == "steal_card":
            # Slepenais darījums: steal 1 random card from target's hand
            if not target_player_id or target_player_id not in self.players:
                self.discard_pile.append(card)
                return {"ok": False, "error": "Invalid target"}

            target = self.players[target_player_id]
            if target["hand"]:
                stolen = random.choice(target["hand"])
                target["hand"].remove(stolen)
                player["hand"].append(stolen)

            self.discard_pile.append(card)
            return {"ok": True}

        if card.effect == "takeover":
            # Pārņemšana: swap entire city (buildings + resources + points)
            if not target_player_id or target_player_id not in self.players:
                self.discard_pile.append(card)
                return {"ok": False, "error": "Invalid target"}

            target = self.players[target_player_id]

            player["resources"], target["resources"] = target["resources"], player["resources"]
            player["buildings"], target["buildings"] = target["buildings"], player["buildings"]
            player["points"], target["points"] = target["points"], player["points"]

            self.discard_pile.append(card)
            return {"ok": True}

        # default: discard
        self.discard_pile.append(card)
        return {"ok": True, "info": "Special card had no implemented effect"}

    # -------------------------------------------------------------------------
    # Serialization for frontend
    # -------------------------------------------------------------------------

    def public_state(self) -> Dict[str, Any]:
        """
        State visible to everyone (no other players' hands).
        """
        players_public = []
        for p in self.players.values():
            players_public.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "hand_size": len(p["hand"]),
                    "resources": p["resources"],
                    "buildings": [
                        {"id": c.id, "name": c.name, "image": c.image}
                        for c in p["buildings"]
                    ],
                    "points": p["points"],
                }
            )

        return {
            "room_code": self.room_code,
            "players": players_public,
            "current_player_id": self.turn_order[self.current_player_index]
            if self.turn_order
            else None,
        }

    def private_state_for(self, player_id: str) -> Dict[str, Any]:
        """
        Full state for a specific player (including their hand).
        """
        p = self.players[player_id]
        return {
            "id": p["id"],
            "name": p["name"],
            "hand": [
                {
                    "id": c.id,
                    "name": c.name,
                    "type": c.type,
                    "image": c.image,
                }
                for c in p["hand"]
            ],
            "resources": p["resources"],
            "buildings": [
                {"id": c.id, "name": c.name, "image": c.image}
                for c in p["buildings"]
            ],
            "points": p["points"],
            "has_defense": p["has_defense"],
        }
