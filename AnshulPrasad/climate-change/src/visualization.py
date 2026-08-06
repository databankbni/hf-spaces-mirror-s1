import matplotlib.pyplot as plt


def plot_forest_loss(loss_dict):
    """
    Generates a bar chart of yearly forest loss.

    Args:
        loss_dict (dict): Dictionary with 'features' containing 'year' and 'loss_area_m2'.

    Returns:
        fig: Matplotlib figure object
    """
    years_list, area_list = [], []

    # Extract year and loss area from each feature
    for f in loss_dict.get("features", []):
        years_list.append(f["properties"]["year"])
        area_list.append(
            f["properties"]["loss_area_m2"] / 10000
        )  # convert m² to hectares

    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(years_list, area_list, color="red")
    ax.set_xlabel("Year")
    ax.set_ylabel("Forest loss (hectares)")
    ax.set_title("Yearly Forest Loss in ROI")
    plt.tight_layout()

    return fig
