package me.robotoraccoon.stablemaster.listeners;

import me.robotoraccoon.stablemaster.StableMaster;
import org.bukkit.NamespacedKey;
import org.bukkit.entity.Camel;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityPortalExitEvent;
import org.bukkit.event.player.PlayerPortalEvent;
import org.bukkit.persistence.PersistentDataContainer;
import org.bukkit.persistence.PersistentDataType;

/**
 * Keeps camels from getting stuck after a dimension change.
 *
 * A camel keeps its LastPoseTick across a portal, but every Bukkit world counts
 * game time separately. Arrive in a world whose game time is lower than that
 * stamp and Camel#getPoseTime() stays negative, so Camel#isInPoseTransition()
 * is true forever: the camel refuses to move, a rider cannot stand it up, its
 * own move control cannot either, and neither can a leash.
 *
 * Vanilla's only escape is Camel#standUpInstantly, which runs when the camel
 * takes damage - and this plugin's protection cancels that damage. So re-stamp
 * the tick here instead. Sitting the camel down and standing it straight back
 * up writes the current world's game time, which is all it needs.
 *
 * @author RobotoRaccoon
 */
public class CamelListener implements Listener {

    /** Standing up takes 52 ticks, so leave room for it before re-stamping again */
    private static final long RESTAMP_COOLDOWN_TICKS = 100L;

    /**
     * Camel arriving from another dimension carries a foreign game-time stamp
     * @param event Event
     */
    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onEntityPortalExit(EntityPortalExitEvent event) {
        restampNextTick(event.getEntity());
    }

    /**
     * A ridden camel travels with its rider, which reports the player, not the
     * camel. Look at what the player is sitting on once the move has happened.
     * @param event Event
     */
    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlayerPortal(PlayerPortalEvent event) {
        restampNextTick(event.getPlayer());
    }

    /**
     * Protection cancelled a player's punch, so run the stand-up vanilla would
     * have run. Also covers /stable release and friends, as those are punch
     * commands. Deliberately not EntityDamageEvent: a repeating source such as
     * fire or suffocation would re-stamp every tick and hold the camel in its
     * pose transition, which pins it exactly like the bug being fixed.
     * @param event Event
     */
    @EventHandler(priority = EventPriority.HIGHEST)
    public void onEntityDamageByEntity(EntityDamageByEntityEvent event) {
        if (event.isCancelled() && event.getDamager() instanceof Player && event.getEntity() instanceof Camel) {
            restamp((Camel) event.getEntity());
        }
    }

    /**
     * Re-stamp once the teleport has actually happened
     * @param entity Entity that travelled, or its rider
     */
    private void restampNextTick(final Entity entity) {
        StableMaster.getPlugin().getServer().getScheduler().runTask(StableMaster.getPlugin(), () -> {
            final Entity target = (entity instanceof Player) ? entity.getVehicle() : entity;
            if (target instanceof Camel) {
                restamp((Camel) target);
            }
        });
    }

    /**
     * Rewrite the camel's pose tick using the game time of the world it is in
     * @param camel Camel
     */
    private void restamp(Camel camel) {
        final long now = camel.getWorld().getGameTime();
        final NamespacedKey key = new NamespacedKey(StableMaster.getPlugin(), "last-pose-restamp");
        final PersistentDataContainer data = camel.getPersistentDataContainer();
        final Long last = data.get(key, PersistentDataType.LONG);

        // A stamp from the future is a stamp from another world's clock, which
        // is the whole problem here, so only an in-range one counts as recent.
        if (last != null && now >= last && now - last < RESTAMP_COOLDOWN_TICKS) {
            return;
        }

        data.set(key, PersistentDataType.LONG, now);

        // ponytail: LastPoseTick is not readable through the API, so re-stamp
        // every time rather than only when the camel is actually stuck. Costs
        // one sit/stand animation. Read the tick via NMS if that ever matters.
        camel.setSitting(true);
        camel.setSitting(false);
    }
}
